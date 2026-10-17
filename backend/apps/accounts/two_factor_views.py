"""Two-factor endpoints: set up, turn on, turn off, new recovery codes, and the
second step of signing in. The rules live in apps/accounts/two_factor.py."""

from __future__ import annotations

import logging

from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services, two_factor
from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.common.errors import (
    AccountSuspended,
    APIError,
    Conflict,
    ValidationFailed,
)
from apps.common.middleware import get_client_ip
from apps.common.throttling import LoginIPThrottle

logger = logging.getLogger("verifygh.accounts.two_factor")


class TwoFactorInvalid(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "TWO_FACTOR_INVALID"
    message = "That code is not right. Check your authenticator app and try again."


class TwoFactorExpired(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "TWO_FACTOR_EXPIRED"
    message = "That sign-in took too long. Please enter your password again."


def challenge_response(user, *, method: str = "password") -> Response:
    """The password step's answer for an account with two-factor on: no session yet."""
    token = two_factor.issue_challenge(user, method=method)
    response = Response({"two_factor_required": True, "challenge": token},
                        status=status.HTTP_200_OK)
    two_factor.set_challenge_cookie(response, token)
    return response


def _code(request) -> str:
    code = str(request.data.get("code") or "").strip()
    if not code:
        raise ValidationFailed("Enter the code from your authenticator app.",
                               details={"fields": {"code": ["Enter a code."]}})
    return code


class TwoFactorVerifyView(APIView):
    """Second step of signing in: the challenge plus a code (or a recovery code)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginIPThrottle]

    def post(self, request):
        from apps.accounts.views import AccountLocked, _auth_response

        code = _code(request)
        token = (request.data.get("challenge")
                 or request.COOKIES.get(two_factor.CHALLENGE_COOKIE, ""))
        data = two_factor.read_challenge(token)
        user = User.objects.filter(pk=data["u"]).first() if data else None
        # A password change, suspension or sign-out-everywhere since the
        # password step bumps the session epoch and voids the challenge.
        if user is None or int(data.get("v", -1)) != int(user.token_version) \
                or not user.is_two_factor_enabled:
            raise TwoFactorExpired()
        if user.is_suspended or not user.is_active:
            raise AccountSuspended()
        if user.is_locked_out:
            raise AccountLocked()

        used = two_factor.verify_code_or_recovery(user, code)
        if not used:
            # The same lockout as a wrong password: a known password does not
            # buy unlimited guesses at the code.
            user.register_failed_login()
            services.record_login_attempt(email=user.email, user=user, successful=False,
                                          request=request, reason="bad_two_factor")
            raise TwoFactorInvalid()

        # One session per challenge.
        try:
            if not cache.add(f"2fa-challenge-used:{data['n']}", 1,
                             two_factor.CHALLENGE_SECONDS):
                raise TwoFactorExpired()
        except TwoFactorExpired:
            raise
        except Exception:
            logger.warning("two_factor_challenge_cache_unavailable")

        user.register_successful_login(ip=get_client_ip(request) or None)
        services.record_login_attempt(email=user.email, user=user, successful=True,
                                      request=request)
        services.track_device(user, request)
        record_audit(actor=user, action="AUTH_LOGIN", target=user, request=request,
                     metadata={"method": data.get("m", "password"), "two_factor": used})
        if used == "recovery":
            logger.warning("two_factor_recovery_code_used", extra={"user_id": str(user.pk)})
        response = _auth_response(user)
        two_factor.clear_challenge_cookie(response)
        return response


class TwoFactorSetupView(APIView):
    """Start enrolment: a new secret, as a QR link and as a key to type."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.is_two_factor_enabled:
            raise Conflict("Two-factor sign-in is already on.", code="TWO_FACTOR_ALREADY_ON")
        secret = two_factor.begin_enrolment(user)
        return Response({"secret": secret,
                         "otpauth_uri": two_factor.provisioning_uri(user.email, secret)})


class TwoFactorEnableView(APIView):
    """Confirm enrolment with a code from the app; returns the recovery codes once."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.is_two_factor_enabled:
            raise Conflict("Two-factor sign-in is already on.", code="TWO_FACTOR_ALREADY_ON")
        if not user.totp_secret:
            raise ValidationFailed("Start the set-up first.", code="TWO_FACTOR_NOT_STARTED")
        if not two_factor.verify_code(user, _code(request)):
            raise TwoFactorInvalid()
        codes = two_factor.enable(user)
        record_audit(actor=user, action="TWO_FACTOR_ENABLED", target=user, request=request)
        return Response({"recovery_codes": codes, "is_two_factor_enabled": True})


def _confirm_identity(request) -> None:
    """The current password (if the account has one) and a code, for changes."""
    user = request.user
    if user.has_usable_password() and not user.check_password(
            str(request.data.get("password") or "")):
        raise ValidationFailed("Your password is not right.",
                               details={"fields": {"password": ["Incorrect password."]}})
    if not two_factor.verify_code_or_recovery(user, _code(request)):
        raise TwoFactorInvalid()


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.is_two_factor_enabled:
            return Response({"is_two_factor_enabled": False})
        _confirm_identity(request)
        two_factor.disable(user)
        record_audit(actor=user, action="TWO_FACTOR_DISABLED", target=user, request=request)
        return Response({"is_two_factor_enabled": False})


class TwoFactorRecoveryCodesView(APIView):
    """A fresh set of recovery codes; the old ones stop working."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.is_two_factor_enabled:
            raise Conflict("Two-factor sign-in is not on.", code="TWO_FACTOR_OFF")
        _confirm_identity(request)
        codes = two_factor.regenerate_recovery_codes(user)
        record_audit(actor=user, action="TWO_FACTOR_RECOVERY_CODES_RENEWED", target=user,
                     request=request)
        return Response({"recovery_codes": codes})
