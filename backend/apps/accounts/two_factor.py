"""Two-factor sign-in: authenticator-app codes (TOTP) and recovery codes.

A SUPER_ADMIN can adjust any balance, so a stolen staff password alone must
not be enough (open since the September audit as O-4). Any account may turn
this on; staff must, when STAFF_TWO_FACTOR_REQUIRED is set (the default
outside development and tests).

* Codes are RFC 6238 TOTP - SHA-1, 6 digits, 30 seconds - which every
  authenticator app speaks. One step either side is accepted for clock drift,
  and a code is accepted once: its time step is recorded and an older or equal
  step is refused, so a code read over someone's shoulder cannot be replayed.
* Recovery codes are shown once, stored only as keyed hashes, and each works
  once.
* Signing in is two requests. The password step returns a signed challenge
  (also set as an httpOnly cookie) bound to the account and its session epoch,
  good for five minutes; the code step exchanges it for a session. A wrong
  code counts towards the same lockout as a wrong password.

Standard library only: hmac, struct, base64.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.common.ids import ALPHABET

DIGITS = 6
PERIOD = 30
#: Steps either side of now that are accepted, for clocks that drift.
DRIFT_STEPS = 1
ISSUER = "VerifyGH"

RECOVERY_CODE_COUNT = 10

CHALLENGE_SALT = "verifygh.two-factor.challenge"
CHALLENGE_SECONDS = 300
CHALLENGE_COOKIE = "vgh_2fa"


# -- TOTP -----------------------------------------------------------------------


def new_secret() -> str:
    """160 random bits, base32 without padding - what authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at(secret: str, step: int) -> str:
    """The code for one 30-second step (RFC 4226 HOTP over the step counter)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step `code` belongs to, within the drift window, or None."""
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digits) != DIGITS or not secret:
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, candidate), digits):
            return candidate
    return None


def provisioning_uri(email: str, secret: str) -> str:
    """The otpauth:// link an authenticator app reads from a QR code."""
    label = quote(f"{ISSUER}:{email}", safe=":@")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}")


def verify_code(user, code: str) -> bool:
    """True once per code: the step is recorded so the same code cannot be reused."""
    from apps.accounts.models import User

    step = matching_step(user.totp_secret, code)
    if step is None:
        return False
    # Atomic compare-and-set on the last step: two requests with one code
    # cannot both win, and an older code than the last one used is refused.
    updated = User.objects.filter(pk=user.pk, totp_last_step__lt=step).update(
        totp_last_step=step)
    if updated:
        user.totp_last_step = step
    return bool(updated)


# -- recovery codes ---------------------------------------------------------------


def _hash_recovery(code: str) -> str:
    normalised = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return hmac.new(settings.SECRET_KEY.encode(), f"recovery:{normalised}".encode(),
                    hashlib.sha256).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(codes to show once, hashes to store)."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [_hash_recovery(code) for code in codes]


def use_recovery_code(user, code: str) -> bool:
    """Spend one recovery code. True if it was valid (and is now used up)."""
    from apps.accounts.models import User

    wanted = _hash_recovery(code)
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        remaining = list(locked.two_factor_recovery_codes or [])
        match = next((h for h in remaining if hmac.compare_digest(h, wanted)), None)
        if match is None:
            return False
        remaining.remove(match)
        User.objects.filter(pk=user.pk).update(two_factor_recovery_codes=remaining)
    user.two_factor_recovery_codes = remaining
    return True


def verify_code_or_recovery(user, code: str) -> str:
    """"totp", "recovery" or "" for a code that is neither."""
    text = str(code or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == DIGITS and len(text.replace(" ", "")) == DIGITS:
        return "totp" if verify_code(user, digits) else ""
    return "recovery" if use_recovery_code(user, text) else ""


# -- enrolment ----------------------------------------------------------------------


def begin_enrolment(user) -> str:
    """A fresh secret, kept but not yet in force until a code from it is confirmed."""
    secret = new_secret()
    type(user).objects.filter(pk=user.pk).update(totp_secret=secret, totp_last_step=0)
    user.totp_secret = secret
    return secret


def enable(user) -> list[str]:
    """Turn two-factor on and return the recovery codes, to be shown once."""
    codes, hashes = new_recovery_codes()
    now = timezone.now()
    type(user).objects.filter(pk=user.pk).update(
        is_two_factor_enabled=True, two_factor_enabled_at=now,
        two_factor_recovery_codes=hashes)
    user.is_two_factor_enabled = True
    user.two_factor_enabled_at = now
    user.two_factor_recovery_codes = hashes
    return codes


def regenerate_recovery_codes(user) -> list[str]:
    codes, hashes = new_recovery_codes()
    type(user).objects.filter(pk=user.pk).update(two_factor_recovery_codes=hashes)
    user.two_factor_recovery_codes = hashes
    return codes


def disable(user) -> None:
    type(user).objects.filter(pk=user.pk).update(
        is_two_factor_enabled=False, two_factor_enabled_at=None, totp_secret="",
        totp_last_step=0, two_factor_recovery_codes=[])
    user.is_two_factor_enabled = False
    user.totp_secret = ""
    user.two_factor_recovery_codes = []


def required_for(user) -> bool:
    """Whether this account must have two-factor before using the admin console."""
    return bool(user and user.is_authenticated and user.is_staff_role
                and settings.VERIFYGH.get("STAFF_TWO_FACTOR_REQUIRED", True))


# -- the sign-in challenge ------------------------------------------------------------


def issue_challenge(user, *, method: str = "password") -> str:
    """A signed, short-lived proof that the first factor passed."""
    return signing.dumps({"u": str(user.pk), "v": int(user.token_version), "m": method,
                          "n": secrets.token_urlsafe(12)}, salt=CHALLENGE_SALT)


def read_challenge(token: str) -> dict | None:
    try:
        data = signing.loads(str(token or ""), salt=CHALLENGE_SALT, max_age=CHALLENGE_SECONDS)
    except signing.BadSignature:
        return None
    return data if isinstance(data, dict) and data.get("u") else None


def set_challenge_cookie(response, token: str) -> None:
    response.set_cookie(
        CHALLENGE_COOKIE, token, max_age=CHALLENGE_SECONDS, httponly=True,
        secure=settings.AUTH_COOKIE_SECURE, samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN, path="/",
    )


def clear_challenge_cookie(response) -> None:
    response.delete_cookie(CHALLENGE_COOKIE, path="/", domain=settings.AUTH_COOKIE_DOMAIN,
                           samesite=settings.AUTH_COOKIE_SAMESITE)
