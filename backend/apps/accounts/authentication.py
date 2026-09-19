"""Cookie-transported JWT authentication with double-submit CSRF and revocation.

Why not localStorage: any XSS on the frontend would hand an attacker a bearer
token. httpOnly cookies cannot be read by script.

Why CSRF is still needed: cookies are sent automatically by the browser, so a
third-party page could trigger an authenticated request. The mitigation is a
second, *readable* cookie whose value must be echoed in the X-CSRF-Token header.
A cross-origin page cannot read our cookie, so it cannot produce the header.

Bearer tokens in the Authorization header are also accepted (for server-to-
server and future API clients) and are exempt from the CSRF check, because they
are not sent ambiently by the browser.

**Revocation.** JWTs are self-contained, so "sign out" is not free. Two
mechanisms cover the two different windows:

* the refresh-token **blacklist** revokes one refresh token - on sign-out, and
  on every rotation, so replaying an old refresh token fails;
* the **token_version** claim revokes *everything a user holds at once*,
  including access tokens already issued. Blacklisting alone would leave a
  stolen access token working for its full lifetime after a password change.

Both are checked on every authenticated request.
"""

from __future__ import annotations

import hmac
import logging
import secrets

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.middleware import bind_user

logger = logging.getLogger("verifygh.auth")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class RevocationCheckedJWTAuthentication(JWTAuthentication):
    """Adds session-epoch and account-status checks to token validation.

    `JWTAuthentication.get_user` only checks `is_active`. That is not enough
    here: a suspended user, or a user who has just changed their password,
    must stop being authenticated on the very next request rather than when
    their access token happens to expire.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        claim = settings.TOKEN_VERSION_CLAIM
        presented = validated_token.get(claim)
        if presented is None or int(presented) != int(user.token_version):
            logger.info(
                "token_revoked_by_version",
                extra={"user_id": str(user.pk), "presented": presented},
            )
            raise AuthenticationFailed(
                "Your session has ended. Please sign in again.", code="token_revoked"
            )

        if user.is_suspended:
            # Rejected here so the token stops working immediately, but surfaced
            # as 403 ACCOUNT_SUSPENDED rather than 401: the session is valid,
            # the account is not. Bouncing a suspended user to the sign-in page
            # would just let them sign in again and learn nothing.
            logger.info("token_rejected_suspended", extra={"user_id": str(user.pk)})
            # Imported here, not at module level: apps.common.errors pulls in
            # DRF's exception handler, which loads DRF settings, which imports
            # this module. A top-level import would be circular.
            from apps.common.errors import AccountSuspended

            raise AccountSuspended()

        return user


class CookieJWTAuthentication(RevocationCheckedJWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            result = super().authenticate(request)
            if result:
                bind_user(result[0])
            return result

        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None

        validated = self.get_validated_token(raw_token)
        user = self.get_user(validated)

        if request.method not in SAFE_METHODS and not _csrf_ok(request):
            raise InvalidToken(
                {"detail": "CSRF check failed. Refresh the page and try again."}
            )

        bind_user(user)
        return user, validated


def _csrf_ok(request) -> bool:
    cookie_value = request.COOKIES.get(settings.AUTH_COOKIE_CSRF, "")
    header_value = request.META.get(settings.AUTH_COOKIE_CSRF_HEADER, "")
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(str(cookie_value), str(header_value))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Issuing and revoking
# ---------------------------------------------------------------------------


def issue_tokens(user) -> tuple[str, str]:
    """Mint an (access, refresh) pair carrying the user's current session epoch.

    `RefreshToken.for_user` also records an OutstandingToken row, which is what
    makes bulk revocation possible later.
    """
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh[settings.TOKEN_VERSION_CLAIM] = int(user.token_version)

    access = refresh.access_token
    access["role"] = user.role
    access[settings.TOKEN_VERSION_CLAIM] = int(user.token_version)

    # for_user() records the OutstandingToken *before* the claims above are
    # added, so the stored copy is a token string we never issued. Revocation
    # keys on jti and works either way, but leaving a phantom token in the table
    # misleads anyone reading it during an incident.
    _sync_outstanding_token(refresh)

    return str(access), str(refresh)


def _sync_outstanding_token(refresh: RefreshToken) -> None:
    try:
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
    except ImportError:  # blacklist app not installed
        return
    try:
        OutstandingToken.objects.filter(jti=refresh[api_settings.JTI_CLAIM]).update(
            token=str(refresh)
        )
    except Exception:
        logger.warning("outstanding_token_sync_failed")


def blacklist_refresh_token(raw_token: str | None) -> bool:
    """Revoke a single refresh token. Never raises.

    Used on sign-out, where failing is not an option: a user must always be
    able to end their session, even if the token they present is already
    expired or malformed.
    """
    if not raw_token:
        return False
    try:
        RefreshToken(raw_token).blacklist()
        return True
    except (TokenError, AttributeError):
        # Expired, already blacklisted, or the blacklist app is not installed.
        return False
    except Exception:
        logger.exception("blacklist_failed")
        return False


#: Two tabs refreshing at the same moment present the same token; the loser
#: sees it already blacklisted. That is a race, not theft, so reuse inside this
#: window is refused without tearing down every session.
REUSE_GRACE_SECONDS = 30


def rotate_refresh_token(refresh: RefreshToken) -> bool:
    """Blacklist `refresh` as part of rotating it. True only for the one caller
    that actually retired it.

    `RefreshToken(raw)` checks the blacklist, but two concurrent requests can
    both pass that check before either writes. The blacklist row is unique per
    token, so exactly one insert wins; the other request must not mint a pair.
    """
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    jti = refresh[api_settings.JTI_CLAIM]
    outstanding, _ = OutstandingToken.objects.get_or_create(
        jti=jti,
        defaults={
            "user_id": refresh.get(api_settings.USER_ID_CLAIM),
            "token": str(refresh),
            "expires_at": refresh.current_time + refresh.lifetime,
        },
    )
    _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
    return created


def detect_refresh_token_reuse(raw_token: str | None):
    """Return the owner if `raw_token` is a genuine refresh token that was
    already rotated or revoked - i.e. somebody is replaying it.

    A replayed refresh token means two parties hold the same credential: the
    user and whoever copied it. We cannot tell which is which, so the safe
    response (RFC 9700, section 4.14.2) is to end every session the user has.

    Returns None for anything that is not a replay: forged, expired or
    malformed tokens, tokens from an older session epoch (already dead by
    token_version, so there is nothing more to revoke), and the benign
    two-tab race inside REUSE_GRACE_SECONDS.
    """
    if not raw_token:
        return None
    try:
        from django.utils import timezone
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.state import token_backend
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        payload = token_backend.decode(raw_token, verify=True)  # signature + expiry
        if payload.get(api_settings.TOKEN_TYPE_CLAIM) != "refresh":
            return None
        entry = (
            BlacklistedToken.objects.select_related("token__user")
            .filter(token__jti=payload.get(api_settings.JTI_CLAIM))
            .first()
        )
    except Exception:
        return None

    if entry is None or entry.token.user is None:
        return None
    user = entry.token.user
    presented = payload.get(settings.TOKEN_VERSION_CLAIM)
    if presented is None or int(presented) != int(user.token_version):
        return None
    age = (timezone.now() - entry.blacklisted_at).total_seconds()
    if age < REUSE_GRACE_SECONDS:
        return None
    return user


def token_version_of(token) -> int | None:
    value = token.get(settings.TOKEN_VERSION_CLAIM)
    return None if value is None else int(value)


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


def _cookie_kwargs() -> dict:
    kwargs = {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "path": "/",
    }
    if settings.AUTH_COOKIE_DOMAIN:
        kwargs["domain"] = settings.AUTH_COOKIE_DOMAIN
    return kwargs


def set_auth_cookies(response, access: str, refresh: str) -> str:
    """Attach auth cookies to a response and return the CSRF token to echo."""
    access_max_age = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    refresh_max_age = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
    common = _cookie_kwargs()

    response.set_cookie(
        settings.AUTH_COOKIE_ACCESS, access, max_age=access_max_age, **common
    )
    response.set_cookie(
        settings.AUTH_COOKIE_REFRESH, refresh, max_age=refresh_max_age, **common
    )

    csrf_token = new_csrf_token()
    # Readable by design: the frontend must copy it into a request header.
    response.set_cookie(
        settings.AUTH_COOKIE_CSRF,
        csrf_token,
        max_age=refresh_max_age,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
        **({"domain": settings.AUTH_COOKIE_DOMAIN} if settings.AUTH_COOKIE_DOMAIN else {}),
    )
    return csrf_token


def clear_auth_cookies(response) -> None:
    kwargs = {"path": "/"}
    if settings.AUTH_COOKIE_DOMAIN:
        kwargs["domain"] = settings.AUTH_COOKIE_DOMAIN
    for name in (
        settings.AUTH_COOKIE_ACCESS,
        settings.AUTH_COOKIE_REFRESH,
        settings.AUTH_COOKIE_CSRF,
    ):
        response.delete_cookie(name, **kwargs)
