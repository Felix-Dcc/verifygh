from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import services
from apps.accounts.authentication import (
    blacklist_refresh_token,
    clear_auth_cookies,
    detect_refresh_token_reuse,
    issue_tokens,
    rotate_refresh_token,
    set_auth_cookies,
    token_version_of,
)
from apps.accounts.models import User
from apps.accounts.serializers import (
    AcceptTermsSerializer,
    ChangePasswordSerializer,
    EmailSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    RegisterSerializer,
    TokenSerializer,
    UpdateProfileSerializer,
    UserSerializer,
)
from apps.audit.models import SuspicionLevel, SuspiciousActivity
from apps.audit.services import flag, record_audit
from apps.common.errors import AccountSuspended, APIError, AuthenticationRequired
from apps.common.middleware import get_client_ip
from apps.common.throttling import (
    EmailVerifyResendThrottle,
    EmailVerifyThrottle,
    LoginIPThrottle,
    LoginThrottle,
    PasswordResetThrottle,
    RegisterThrottle,
)

logger = logging.getLogger("verifygh.auth")


def _auth_response(user: User, status_code: int = status.HTTP_200_OK) -> Response:
    access, refresh = issue_tokens(user)
    response = Response(
        {"user": UserSerializer(user).data},
        status=status_code,
    )
    csrf_token = set_auth_cookies(response, access, refresh)
    # Also returned in the body so a non-browser client can use bearer auth.
    response.data["csrf_token"] = csrf_token
    return response


class RegisterView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [RegisterThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = services.register_user(
            email=data["email"],
            password=data["password"],
            full_name=data.get("full_name", ""),
            phone=data.get("phone", ""),
            accepted_terms=data["accepted_terms"],
            referral_code=data.get("referral_code", ""),
            request=request,
        )
        record_audit(
            actor=user, action="AUTH_REGISTER", target=user, request=request,
            metadata={"email": user.email},
        )
        return _auth_response(user, status.HTTP_201_CREATED)


class EmailDeliveryFailed(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "EMAIL_DELIVERY_FAILED"
    # Deliberately says nothing about which provider, or why: that is an
    # operational detail, and the user's only useful action is to try again.
    message = "We could not send that email just now. Please try again in a few minutes."


class LoginFailed(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"
    message = "That email or password is incorrect."


class AccountLocked(APIError):
    status_code = status.HTTP_423_LOCKED
    code = "ACCOUNT_LOCKED"
    message = "Too many failed attempts. Try again in a few minutes."


class LoginView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    # Per-(IP, email) stops guessing one account's password; per-IP stops one
    # address trying a leaked credential list against thousands of accounts.
    throttle_classes = [LoginIPThrottle, LoginThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]

        user = User.objects.filter(email__iexact=email).first()

        if user and user.is_locked_out:
            services.record_login_attempt(
                email=email, user=user, successful=False, request=request, reason="locked"
            )
            raise AccountLocked()

        authenticated = authenticate(request, username=email, password=password)

        if authenticated is None:
            if user is not None:
                user.register_failed_login()
            services.record_login_attempt(
                email=email, user=user, successful=False, request=request,
                reason="bad_credentials",
            )
            # Same error whether the address exists or not.
            raise LoginFailed()

        if authenticated.is_suspended:
            services.record_login_attempt(
                email=email, user=authenticated, successful=False, request=request,
                reason="suspended",
            )
            raise AccountSuspended()

        authenticated.register_successful_login(ip=get_client_ip(request) or None)
        services.record_login_attempt(
            email=email, user=authenticated, successful=True, request=request
        )
        services.track_device(authenticated, request)
        record_audit(actor=authenticated, action="AUTH_LOGIN", target=authenticated,
                     request=request)
        return _auth_response(authenticated)


class RefreshView(APIView):
    permission_classes = [AllowAny]
    # Reads the refresh cookie directly; the access cookie is irrelevant here.
    authentication_classes: list = []

    def post(self, request):
        raw = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH) or request.data.get("refresh")
        if not raw:
            raise AuthenticationRequired("Your session has expired. Please sign in again.")

        try:
            # Raises if the token is expired, tampered with, or blacklisted -
            # which is what makes a replayed refresh token fail.
            refresh = RefreshToken(raw)
            user = User.objects.get(pk=refresh["user_id"])
        except (TokenError, KeyError, User.DoesNotExist) as exc:
            _handle_possible_reuse(request, raw)
            raise AuthenticationRequired("Your session has expired. Please sign in again.") from exc

        # A refresh token issued before a password change or a suspension must
        # not mint a fresh pair.
        if token_version_of(refresh) != int(user.token_version):
            logger.info("refresh_rejected_stale_version", extra={"user_id": str(user.pk)})
            raise AuthenticationRequired("Your session has ended. Please sign in again.")

        if user.is_suspended or not user.is_active:
            raise AccountSuspended()

        # Rotate: the presented token is revoked as the new pair is issued, so
        # a copy stolen earlier is now useless. Only the request that actually
        # retires the token gets a new pair - a concurrent twin gets nothing.
        if not rotate_refresh_token(refresh):
            raise AuthenticationRequired("Your session has expired. Please sign in again.")

        return _auth_response(user)


def _handle_possible_reuse(request, raw) -> None:
    """A rotated refresh token came back: end every session the owner has."""
    user = detect_refresh_token_reuse(raw)
    if user is None:
        return
    user.revoke_all_sessions()
    logger.warning("refresh_token_reuse_detected", extra={"user_id": str(user.pk)})
    flag(
        user=user,
        kind=SuspiciousActivity.Kind.TOKEN_REUSE,
        level=SuspicionLevel.HIGH,
        description="A refresh token was presented after it had been rotated or revoked. "
                    "All sessions were ended.",
        evidence={"ip": get_client_ip(request)},
        dedupe_hours=0,
    )
    record_audit(actor=user, action="AUTH_REFRESH_REUSE", target=user, request=request,
                 metadata={"sessions_revoked": True})


class LogoutView(APIView):
    permission_classes = [AllowAny]
    # Signing out must always succeed. Requiring a valid session to end a
    # session is how users get stuck with a cookie they cannot clear.
    authentication_classes: list = []

    def post(self, request):
        # Clearing the cookie only stops *this* browser sending it. Blacklisting
        # revokes the token itself, so a copy taken elsewhere is dead too.
        raw = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH) or request.data.get("refresh")
        revoked = blacklist_refresh_token(raw)

        response = Response({"detail": "Signed out."}, status=status.HTTP_200_OK)
        clear_auth_cookies(response)
        record_audit(action="AUTH_LOGOUT", request=request, metadata={"revoked": revoked})
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})

    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record_audit(actor=request.user, action="PROFILE_UPDATE", target=request.user,
                     request=request, metadata={"fields": list(serializer.validated_data)})
        return Response({"user": UserSerializer(request.user).data})


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])

        # Changing a password must end every other session immediately - that is
        # the whole point of changing it after a suspected compromise.
        revoked = user.revoke_all_sessions()
        logger.info(
            "sessions_revoked", extra={"user_id": str(user.pk), "reason": "password_change",
                                       "tokens": revoked},
        )

        from apps.notifications.services import notify

        notify(
            user,
            event="SECURITY_ALERT",
            title="Your password was changed",
            body="Your VerifyGH password was just changed.",
            channels=("EMAIL", "IN_APP"),
        )
        record_audit(actor=user, action="PASSWORD_CHANGE", target=user, request=request)
        # Issue a fresh pair for the caller, so the person who just changed their
        # password is not signed out of the tab they did it in.
        user.refresh_from_db()
        return _auth_response(user)


class SendEmailVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        if request.user.is_email_verified:
            return Response({"detail": "Your email address is already verified."})

        delivered = services.send_verification_email(
            request.user, ip=get_client_ip(request) or None
        )
        if not delivered:
            # The provider refused it. Saying "sent" would leave the user
            # waiting for an email that is not coming.
            raise EmailDeliveryFailed()
        return Response({"detail": "Verification email sent."})


class ConfirmEmailVerificationView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.verify_email(serializer.validated_data["token"])
        record_audit(actor=user, action="EMAIL_VERIFIED", target=user, request=request)
        return Response({"user": UserSerializer(user).data})


class ResendVerificationView(APIView):
    """Ask for another verification email, without being signed in.

    Someone who registered, lost the email and closed the tab has no session to
    authenticate with, so this has to be reachable anonymously. The response is
    therefore identical in every case - existing address, unknown address,
    already-verified address - because a caller able to tell them apart could
    use this endpoint to test whether an address has a VerifyGH account.
    """

    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [EmailVerifyResendThrottle]

    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resend_verification_email(
            serializer.validated_data["email"], request=request
        )
        return Response(
            {
                "detail": "If an account exists with this email address and still needs "
                          "verifying, a verification email has been sent."
            }
        )


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"], request=request)
        # Deliberately identical whether or not the account exists.
        return Response(
            {"detail": "If that email is registered, a reset link is on its way."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.reset_password(
            serializer.validated_data["token"], serializer.validated_data["new_password"]
        )
        record_audit(actor=user, action="PASSWORD_RESET", target=user, request=request)
        return Response({"detail": "Your password has been reset. You can now sign in."})


class AcceptTermsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AcceptTermsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
        user.accepted_terms_at = timezone.now()
        user.save(update_fields=["accepted_terms_version", "accepted_terms_at", "updated_at"])
        record_audit(
            actor=user, action="TERMS_ACCEPTED", target=user, request=request,
            metadata={"version": user.accepted_terms_version},
        )
        return Response({"user": UserSerializer(user).data})
