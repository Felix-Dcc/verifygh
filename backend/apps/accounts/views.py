from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import google, services, turnstile
from apps.accounts.authentication import (
    blacklist_refresh_token,
    clear_auth_cookies,
    detect_refresh_token_reuse,
    issue_tokens,
    recover_session,
    remember_rotation,
    revoke_access_token,
    rotate_refresh_token,
    set_auth_cookies,
    token_version_of,
)
from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.accounts.serializers import (
    AcceptTermsSerializer,
    ChangeOwnEmailSerializer,
    ChangePasswordSerializer,
    EmailCodeSerializer,
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
from apps.common.errors import (
    AccountSuspended,
    APIError,
    AuthenticationRequired,
    ValidationFailed,
)
from apps.common.middleware import get_client_ip
from apps.common.throttling import (
    EmailChangeThrottle,
    EmailCodeThrottle,
    EmailVerifyResendThrottle,
    EmailVerifyThrottle,
    LoginIPThrottle,
    LoginThrottle,
    PasswordResetThrottle,
    RegisterThrottle,
)

logger = logging.getLogger("verifygh.auth")


def _auth_response(user: User, status_code: int = status.HTTP_200_OK, *,
                   tokens: tuple[str, str] | None = None) -> Response:
    access, refresh = tokens or issue_tokens(user)
    response = Response(
        {"user": UserSerializer(user).data},
        status=status_code,
    )
    csrf_token = set_auth_cookies(response, access, refresh)
    # Also returned in the body so a non-browser client can use bearer auth.
    response.data["csrf_token"] = csrf_token
    return response


#: For the views that sign a browser in. An HTML form on another site can post
#: a urlencoded or multipart body with no CORS preflight, and these views need
#: no session - so without this, another site could sign a visitor into the
#: attacker's account (login CSRF) and watch them top it up. A JSON body cannot
#: be sent cross-site without a preflight, which CORS refuses.
JSON_ONLY = [JSONParser]


class RegisterView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [RegisterThrottle]
    parser_classes = JSON_ONLY

    def post(self, request):
        # Before anything else: the form's own errors ("an account with this
        # email already exists") are not for bots.
        turnstile.require_human(request, request.data.get("turnstile_token"), action="register")
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
    parser_classes = JSON_ONLY

    def post(self, request):
        # Before any password is tried, so a bot's guesses neither reach the
        # hasher nor lock the real owner out.
        turnstile.require_human(request, request.data.get("turnstile_token"), action="login")
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

        # Exact first, then without surrounding whitespace - see
        # services.password_candidates for why the second try exists. Counted
        # as one attempt either way, so it cannot be used to double the guesses
        # an attacker gets before the lockout.
        authenticated = None
        for candidate in services.password_candidates(password):
            authenticated = authenticate(request, username=email, password=candidate)
            if authenticated is not None:
                break

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
            # The same browser whose last renewal reply was lost: send it the
            # replacement it never received, rather than signing it out.
            recovered = recover_session(raw, request)
            if recovered is not None:
                user, tokens = recovered
                logger.info("refresh_rotation_recovered", extra={"user_id": str(user.pk)})
                return _auth_response(user, tokens=tokens)
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

        tokens = issue_tokens(user)
        remember_rotation(refresh, tokens[1], request)
        return _auth_response(user, tokens=tokens)


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

        # The access token too. Blacklisting the refresh token stops new
        # sessions being made, but the access token already issued would
        # otherwise keep authenticating for its full lifetime - so a copy lifted
        # from a shared machine would survive the customer logging out.
        header = request.META.get("HTTP_AUTHORIZATION", "")
        bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
        access = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS) or bearer
        revoke_access_token(access)

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
    """Email a new code (and link). Not more than once per EMAIL_CODE_RESEND_SECONDS."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        if request.user.is_email_verified:
            return Response({"detail": "Your email address is already verified."})

        result = services.send_verification_code(
            request.user, ip=get_client_ip(request) or None
        )
        if not result["sent"]:
            return Response({**result, "detail": "We sent you a code a moment ago."})
        if not result.get("delivered"):
            # The provider refused it. Saying "sent" would leave the user
            # waiting for an email that is not coming.
            raise EmailDeliveryFailed()
        return Response({**result, "detail": "Verification email sent."})


class EmailVerificationStatusView(APIView):
    """For the verify screen: is a code on its way, and when may it resend."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(services.verification_status(request.user))


class ConfirmEmailCodeView(APIView):
    """The 6-digit code from the email, typed into the app by the signed-in user."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailCodeThrottle]

    def post(self, request):
        serializer = EmailCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        was_verified = request.user.is_email_verified
        user = services.verify_email_code(request.user, serializer.validated_data["code"])
        if not was_verified:
            record_audit(actor=user, action="EMAIL_VERIFIED", target=user, request=request,
                         metadata={"method": "code"})
        return Response({"user": UserSerializer(user).data})


class ChangeOwnEmailView(APIView):
    """Correct a mistyped address while it is still unverified."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailChangeThrottle]

    def post(self, request):
        serializer = ChangeOwnEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.change_own_unverified_email(
            user=request.user, new_email=serializer.validated_data["new_email"],
            password=serializer.validated_data["password"], request=request,
        )
        return Response({"user": UserSerializer(user).data,
                         **services.verification_status(user)})


class ConfirmEmailVerificationView(APIView):
    permission_classes = [AllowAny]
    # Authenticates from the request body, not from the session. Ignoring the
    # access cookie keeps the CSRF gate out of a flow it has no part in.
    authentication_classes: list = []
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        try:
            user = services.verify_email(token)
        except ValidationFailed:
            # Spent or expired, but the address is verified: say so, not "invalid".
            user = services.verified_owner(token)
            if user is None:
                raise
            return Response({"user": UserSerializer(user).data, "already_verified": True})
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


class SignInOptionsView(APIView):
    """Which ways of signing in this deployment offers, for the sign-in pages."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"google": google.is_configured()})


# ---------------------------------------------------------------------------
# Sign in with Google (apps/accounts/google.py)
# ---------------------------------------------------------------------------

#: Holds the state, nonce and PKCE verifier between the two legs. Signed, so it
#: cannot be forged; HttpOnly, host-only and scoped to the callback path.
GOOGLE_PENDING_COOKIE = "vgh_google"
GOOGLE_PENDING_SALT = "verifygh.google-sign-in"
GOOGLE_PENDING_SECONDS = 600


def _frontend(path: str) -> str:
    return str(settings.VERIFYGH["FRONTEND_URL"]).rstrip("/") + path


def _safe_next(raw) -> str:
    """A path on our own site to land on afterwards - never another origin."""
    value = str(raw or "").strip()
    if (
        value.startswith("/")
        and not value.startswith("//")
        and len(value) <= 300
        and not any(char in value for char in "\\\r\n\t")
    ):
        return value
    return "/dashboard"


def _callback_path() -> str:
    return reverse("v1:accounts:google-callback")


class _GoogleRedirectView(APIView):
    """Both legs are browser navigations, so every outcome is a redirect.

    A JSON error (a rate limit, say) would leave the customer on a page of raw
    API output; instead they land back on the form with a short reason.
    """

    permission_classes = [AllowAny]
    # Not authenticated from cookies: the state cookie is what ties the two legs
    # together, and the CSRF gate has no part in a GET navigation.
    authentication_classes: list = []
    throttle_classes = [LoginIPThrottle]

    def handle_exception(self, exc):
        logger.info("google_sign_in_refused", extra={"error": type(exc).__name__})
        return self.fail("busy" if getattr(exc, "status_code", 0) == 429 else "failed")

    def fail(self, reason: str, *, intent: str = "signin") -> HttpResponseRedirect:
        page = "/register" if intent == "signup" else "/login"
        response = HttpResponseRedirect(_frontend(f"{page}?google={reason}"))
        response.delete_cookie(GOOGLE_PENDING_COOKIE, path=_callback_path())
        return response


class GoogleStartView(_GoogleRedirectView):
    """Send the browser to Google's account chooser."""

    def get(self, request):
        intent = "signup" if request.GET.get("intent") == "signup" else "signin"
        if not google.is_configured():
            return self.fail("unavailable", intent=intent)

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier, challenge = google.new_pkce_pair()
        referral = str(request.GET.get("ref") or "")[:16]
        pending = {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "next": _safe_next(request.GET.get("next")),
            "intent": intent,
            # Only the sign-up form asks for the terms; it sends terms=1 once ticked.
            "terms": intent == "signup" and request.GET.get("terms") == "1",
            "ref": referral if referral.isalnum() else "",
        }

        response = HttpResponseRedirect(
            google.authorization_url(state=state, nonce=nonce, code_challenge=challenge)
        )
        response.set_cookie(
            GOOGLE_PENDING_COOKIE,
            signing.dumps(pending, salt=GOOGLE_PENDING_SALT),
            max_age=GOOGLE_PENDING_SECONDS,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            # Lax, not Strict: the return from accounts.google.com is a
            # cross-site navigation, and the cookie has to come with it.
            samesite="Lax",
            path=_callback_path(),
        )
        return response


class GoogleCallbackView(_GoogleRedirectView):
    """Google sends the browser back here with a code; sign in and go to the app."""

    def get(self, request):
        try:
            pending = signing.loads(
                request.COOKIES.get(GOOGLE_PENDING_COOKIE, ""),
                salt=GOOGLE_PENDING_SALT,
                max_age=GOOGLE_PENDING_SECONDS,
            )
        except signing.BadSignature:
            # Missing, tampered with, or older than ten minutes.
            return self.fail("expired")
        intent = pending.get("intent", "signin")

        # The state ties this callback to the browser that started it, so no one
        # can sign a visitor in to an account of theirs (login CSRF).
        if not secrets.compare_digest(str(request.GET.get("state") or ""), pending["state"]):
            return self.fail("expired", intent=intent)
        if request.GET.get("error"):
            # Most often access_denied: they closed the chooser or said no.
            return self.fail("cancelled", intent=intent)
        code = str(request.GET.get("code") or "")
        if not code or not google.is_configured():
            return self.fail("failed", intent=intent)

        try:
            identity = google.exchange_code(
                code, code_verifier=pending["verifier"], nonce=pending["nonce"]
            )
            user, created = services.sign_in_with_google(
                subject=identity.subject,
                email=identity.email,
                name=identity.name,
                accepted_terms=bool(pending.get("terms")),
                referral_code=pending.get("ref", ""),
                request=request,
            )
        except google.GoogleSignInError as exc:
            return self.fail(exc.reason, intent=intent)
        except services.GoogleAccountConflict:
            logger.warning("google_sign_in_conflict")
            return self.fail("conflict", intent=intent)

        if user.is_suspended or not user.is_active:
            services.record_login_attempt(
                email=user.email, user=user, successful=False, request=request,
                reason="suspended",
            )
            return self.fail("suspended", intent=intent)

        # Google has proved who this is, so a password lockout - which exists
        # to stop guessing - is cleared like any other successful sign-in.
        user.register_successful_login(ip=get_client_ip(request) or None)
        services.record_login_attempt(email=user.email, user=user, successful=True,
                                      request=request)
        services.track_device(user, request)
        record_audit(
            actor=user, action="AUTH_REGISTER" if created else "AUTH_LOGIN", target=user,
            request=request, metadata={"method": "google"},
        )

        destination = pending["next"] if user.role == Role.USER else "/admin"
        response = HttpResponseRedirect(_frontend(destination))
        access, refresh = issue_tokens(user)
        set_auth_cookies(response, access, refresh)
        response.delete_cookie(GOOGLE_PENDING_COOKIE, path=_callback_path())
        return response
