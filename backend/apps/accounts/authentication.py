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
* the **access denylist** revokes *one* access token by its `jti`, and is what
  sign-out uses. Without it, signing out killed the refresh token but left its
  paired access token authenticating for up to ACCESS_TOKEN_LIFETIME - a copy
  taken from a shared computer kept working after the customer had logged out.
  token_version would close that too, but it would also sign the customer out
  of every other device, which is not what "Log out" means.

All three are checked on every authenticated request.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets

from django.conf import settings
from django.core.cache import cache
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.common.middleware import bind_user

logger = logging.getLogger("verifygh.auth")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

#: Cache key for a revoked access token. Keyed on the jti, never the token
#: itself: the cache is not a place to keep live credentials.
_REVOKED_ACCESS_KEY = "auth:revoked_access:{jti}"


def revoke_access_token(raw_token: str | None) -> bool:
    """Stop one access token working, for the rest of its natural life.

    Only as long as it would have lived anyway: past `exp` the token is refused
    on its own, so remembering it any longer would just be cache garbage.
    Returns False for a token that is missing, malformed or already expired -
    none of which needs revoking.
    """
    if not raw_token:
        return False
    try:
        token = AccessToken(raw_token)
    except TokenError:
        return False

    import time

    jti = token.get(jwt_settings.JTI_CLAIM)
    exp = token.get("exp")
    if not jti or not exp:
        return False
    remaining = int(exp - time.time())
    if remaining <= 0:
        return False

    try:
        cache.set(_REVOKED_ACCESS_KEY.format(jti=jti), 1, timeout=remaining)
    except Exception:
        # Losing this is a narrower window, not an open door: the refresh token
        # is still blacklisted in the database, so no new session can be made,
        # and this token expires on its own within ACCESS_TOKEN_LIFETIME.
        logger.error("access_revocation_store_unavailable", exc_info=True)
        return False
    return True


def _access_revoked(validated_token) -> bool:
    jti = validated_token.get(jwt_settings.JTI_CLAIM)
    if not jti:
        return False
    try:
        return bool(cache.get(_REVOKED_ACCESS_KEY.format(jti=jti)))
    except Exception:
        # Fails open, loudly, for the same reason the throttles do: failing
        # closed would turn a Redis blip into every signed-in customer being
        # logged out at once. The token is short-lived and its refresh token is
        # already dead, so the exposure is bounded.
        logger.error("access_revocation_check_unavailable", exc_info=True)
        return False


class RevocationCheckedJWTAuthentication(JWTAuthentication):
    """Adds session-epoch and account-status checks to token validation.

    `JWTAuthentication.get_user` only checks `is_active`. That is not enough
    here: a suspended user, or a user who has just changed their password,
    must stop being authenticated on the very next request rather than when
    their access token happens to expire.
    """

    def get_user(self, validated_token):
        # Before the user lookup: a signed-out token should cost a cache read,
        # not a database query.
        if _access_revoked(validated_token):
            logger.info("token_revoked_by_signout")
            raise AuthenticationFailed(
                "Your session has ended. Please sign in again.", code="token_revoked"
            )

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

#: How long a rotation is remembered so a lost reply can be recovered: the
#: retired token's own lifetime. A renewal that takes seconds on mobile data is
#: often abandoned - the customer taps on, the browser drops the reply and its
#: new cookies, and the server has already retired the token the browser still
#: holds. That browser comes back with it whenever the customer next visits -
#: 41 minutes later in one case on 5 Oct, after a 10-minute window had closed -
#: which looked like theft and signed the customer out of everything.
ROTATION_RECOVERY_SECONDS = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

#: Recoveries that revoke a session and issue a new one, per account per day.
#: The same browser can come back with a token that has since moved on - an
#: iPhone presented, at 18:53 on 6 Oct, the very token our 18:25 recovery had
#: revoked, and at 04:04 on 7 Oct one it had renewed past. Both are recovered.
#: But a thief with an identical browser could use the same path to take turns
#: with the customer, so past this many in a day the next one is theft.
ROTATION_RECOVERY_DAILY_LIMIT = 3

#: The same, when the browser is not merely the same kind but the very same
#: user agent, versions included, that the session was renewed from. Some
#: iPhones lose renewals far more often than three times a day: on 9 Oct one
#: was recovered at 09:10 and, its three spent, signed out as stolen at 09:22 -
#: then signed straight back in with its password. A thief would now need the
#: customer's exact user agent, and is still held to this many turns a day.
ROTATION_RECOVERY_EXACT_DAILY_LIMIT = 10

#: How far a recovery follows the rotation notes to the current token.
ROTATION_CHAIN_LIMIT = 20


def _rotation_key(jti: str) -> str:
    return f"refresh-rotated:{jti}"


def client_fingerprint(request) -> str:
    """The browser behind a request, to tell "the same browser asking again"
    from someone else holding a copied token.

    The browser only, not the network: a phone's address changes as it moves
    between mobile towers and Wi-Fi, and the customer coming back an hour later
    is still the same browser. How a thief with an identical browser is still
    caught is recover_session.

    Version numbers are left out. Production, 8 Oct: an iPhone came back a week
    after its last renewal - Safari had updated in between, so the full user
    agent no longer matched and its own session read as theft. Safari 26.4 and
    26.6 are the same browser; Safari and Chrome, or an iPhone and an Android
    phone, still are not.
    """
    import hashlib

    return hashlib.sha256(_browser_family(request).encode()).hexdigest()


def _browser_family(request) -> str:
    """The user agent with every version number replaced: `iPhone OS 18_7`,
    `Version/26.4` and `Chrome/152.0.7977.64` become `iPhone OS #`, `Version/#`
    and `Chrome/#`."""
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
    return re.sub(r"\d+(?:[._]\d+)*", "#", user_agent)


def _legacy_client_fingerprint(request) -> str:
    """The full user agent, as notes written before 8 Oct recorded it. Still
    accepted: it is the stricter match, so it can never let in a browser the
    current one would refuse."""
    import hashlib

    user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
    return hashlib.sha256(user_agent.encode()).hexdigest()


def remember_rotation(old: RefreshToken, new_refresh: str, request) -> None:
    """Note which token replaced `old`, and for whom, for ROTATION_RECOVERY_SECONDS."""
    from rest_framework_simplejwt.settings import api_settings

    try:
        _note_rotation(old[api_settings.JTI_CLAIM], new_refresh, request)
    except Exception:
        # Losing the note only means a lost reply cannot be recovered.
        logger.warning("refresh_rotation_note_failed")


def _note_rotation(old_jti: str, new_refresh: str, request) -> None:
    from django.core.cache import cache
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.state import token_backend

    successor = token_backend.decode(new_refresh, verify=True)[api_settings.JTI_CLAIM]
    cache.set(_rotation_key(old_jti),
              {"successor": successor, "client": client_fingerprint(request),
               "exact": _legacy_client_fingerprint(request)},
              ROTATION_RECOVERY_SECONDS)


def _current_token(start_jti: str):
    """The OutstandingToken the rotation notes lead to from `start_jti`: the
    first one not yet retired. None when the trail breaks (a note expired, a
    token was signed out) - the session cannot be traced, so it is not
    recovered."""
    from django.core.cache import cache
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    jti = start_jti
    for _ in range(ROTATION_CHAIN_LIMIT):
        note = cache.get(_rotation_key(jti))
        if not note:
            return None
        token = (OutstandingToken.objects.select_related("user")
                 .filter(jti=note.get("successor")).first())
        if token is None or token.user is None:
            return None
        if not BlacklistedToken.objects.filter(token=token).exists():
            return token
        jti = token.jti
    return None


def _within_recovery_limit(user, *, exact: bool = False) -> bool:
    """Count one more recovery for `user`; False once the day's limit is passed.

    One count per account, whichever browser: a merely similar browser is
    refused once three have been used today, the exact same one once ten have.
    """
    from django.core.cache import cache

    key = f"refresh-recoveries:{user.pk}"
    limit = ROTATION_RECOVERY_EXACT_DAILY_LIMIT if exact else ROTATION_RECOVERY_DAILY_LIMIT
    try:
        cache.add(key, 0, 24 * 3600)
        return cache.incr(key) <= limit
    except Exception:
        return False  # cannot count: no recovery, which is how it worked before


def recover_lost_rotation(raw_token: str | None, request):
    """(user, successor, current, seconds since the rotation, exact) when a
    retired token comes back from the browser that retired it; None otherwise.
    `exact` is True when it is the very same user agent, versions included.

    `successor` is the token that directly replaced it; `current` is where the
    session stands now, following the rotation notes - the successor itself
    when its reply was simply lost, a later token when the browser renewed on
    since (in another tab, or with a cookie it later lost). Only the browser
    named in the note qualifies: a token presented by any other browser stays
    theft. What the caller does with a same-browser match - and how a thief
    with an identical browser is still caught - is recover_session.
    """
    if not raw_token:
        return None
    try:
        from django.core.cache import cache
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.state import token_backend
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        payload = token_backend.decode(raw_token, verify=True)
        if payload.get(api_settings.TOKEN_TYPE_CLAIM) != "refresh":
            return None
        note = cache.get(_rotation_key(payload.get(api_settings.JTI_CLAIM)))
        if not note or note.get("client") not in (client_fingerprint(request),
                                                  _legacy_client_fingerprint(request)):
            return None
        successor = (OutstandingToken.objects.select_related("user")
                     .filter(jti=note.get("successor")).first())
        if successor is None or successor.user is None:
            return None
        current = _current_token(payload.get(api_settings.JTI_CLAIM))
        if current is None or current.user_id != successor.user_id:
            return None
        user = successor.user
        presented = payload.get(settings.TOKEN_VERSION_CLAIM)
        if presented is None or int(presented) != int(user.token_version):
            return None
        if user.is_suspended or not user.is_active:
            return None
        # Measured from when the presented token was retired - the same clock
        # the two-tab race grace in detect_refresh_token_reuse uses.
        from django.utils import timezone

        retired = (BlacklistedToken.objects.filter(token__jti=payload.get(api_settings.JTI_CLAIM))
                   .values_list("blacklisted_at", flat=True).first())
        age = (timezone.now() - retired).total_seconds() if retired else 0.0
        # Notes from before 9 Oct carry no "exact"; those written before 8 Oct
        # recorded the full user agent as "client", which is the same test.
        exact_fp = _legacy_client_fingerprint(request)
        exact = exact_fp in (note.get("exact"), note.get("client"))
        return user, successor, current, max(0.0, age), exact
    except Exception:
        return None


def recover_session(raw_token: str | None, request):
    """(user, (access, refresh)) for a browser that came back with a token
    its own session has moved past.

    Within REUSE_GRACE_SECONDS it is two tabs racing, and the loser gets the
    replacement the winner already has - if nothing has renewed since.

    Later, whatever is current is revoked and a new pair issued, and both the
    presented token and the revoked one are noted as replaced by it. So
    whichever copy this browser holds next - the one it lost, or the one it
    found again - leads to the live session instead of reading as theft. If
    the other copy is a thief's, the thief loses the session now; a thief on
    another browser is caught at its next renewal (the note names this
    browser), and one on an identical browser can take turns with the customer
    only ROTATION_RECOVERY_DAILY_LIMIT times a day before it is caught
    (ROTATION_RECOVERY_EXACT_DAILY_LIMIT if it copies the exact user agent).
    """
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

    recovered = recover_lost_rotation(raw_token, request)
    if recovered is None:
        return None
    user, successor, current, age, exact = recovered
    if age < REUSE_GRACE_SECONDS:
        if current.pk != successor.pk:
            return None  # renewed on already: a refusal, and not theft (the race grace)
        return user, (access_for(user, successor.token), successor.token)
    if not _within_recovery_limit(user, exact=exact):
        logger.warning("refresh_recovery_limit_reached",
                       extra={"user_id": str(user.pk), "exact_browser": exact})
        return None
    BlacklistedToken.objects.get_or_create(token=current)
    tokens = issue_tokens(user)
    try:
        presented = RefreshToken(raw_token, verify=False)
        _note_rotation(presented[api_settings.JTI_CLAIM], tokens[1], request)
        _note_rotation(current.jti, tokens[1], request)
    except Exception:
        logger.warning("refresh_rotation_note_failed")
    return user, tokens


def access_for(user, refresh_token: str) -> str:
    """A fresh access token from an existing refresh token, with our claims."""
    access = RefreshToken(refresh_token).access_token
    access["role"] = user.role
    access[settings.TOKEN_VERSION_CLAIM] = int(user.token_version)
    return str(access)


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
