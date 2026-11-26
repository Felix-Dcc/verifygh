"""Admin API keys: making them, checking them on every request, revoking them.

A key looks like ``vgh_ak_<prefix>_<secret>``. The prefix is public and finds
the row; the whole key is compared against a SHA-256 hash in constant time.
SHA-256 rather than a password hash because the secret is 256 random bits -
there is nothing to brute-force, and a slow hash on every API call would only
cost latency.

See AdminApiKey for what a key may and may not do.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from apps.accounts.models import AdminApiKey, ApiKeyAccess
from apps.common.errors import APIError

logger = logging.getLogger("verifygh.auth")

KEY_MARKER = "vgh_ak_"
ALLOWED_DAYS = (1, 7, 30, 90)
MAX_ACTIVE_PER_OWNER = 5

#: Where a key works: the admin API, and nothing that manages keys.
ADMIN_PATH = "/api/v1/admin/"
KEYS_PATH = "/api/v1/admin/api-keys/"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

#: How often last_used_at is written: often enough to read, not on every call.
_TOUCH_EVERY = timedelta(minutes=1)


class TooManyKeys(APIError):
    code = "TOO_MANY_API_KEYS"
    message = (f"You already have {MAX_ACTIVE_PER_OWNER} active keys. "
               "Revoke one you no longer use first.")


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def looks_like_key(raw_token: bytes | str | None) -> bool:
    if raw_token is None:
        return False
    if isinstance(raw_token, bytes):
        return raw_token.startswith(KEY_MARKER.encode())
    return raw_token.startswith(KEY_MARKER)


def active_keys(owner):
    return AdminApiKey.objects.filter(
        owner=owner, revoked_at__isnull=True, expires_at__gt=timezone.now(),
        token_version=owner.token_version,
    )


@transaction.atomic
def create_key(*, owner, name: str, access: str, days: int) -> tuple[AdminApiKey, str]:
    """(the stored key, the full key to show once)."""
    if days not in ALLOWED_DAYS:
        raise ValueError(f"days must be one of {ALLOWED_DAYS}")
    # Lock the owner so two simultaneous requests cannot both slip under the cap.
    type(owner).objects.select_for_update().filter(pk=owner.pk).first()
    if active_keys(owner).count() >= MAX_ACTIVE_PER_OWNER:
        raise TooManyKeys()

    prefix = secrets.token_hex(4)
    raw = f"{KEY_MARKER}{prefix}_{secrets.token_urlsafe(32)}"
    key = AdminApiKey.objects.create(
        owner=owner, name=name.strip(), prefix=prefix, key_hash=_hash(raw),
        access=access if access in ApiKeyAccess.values else ApiKeyAccess.READ,
        expires_at=timezone.now() + timedelta(days=days),
        token_version=owner.token_version,
    )
    return key, raw


def revoke_key(key: AdminApiKey, *, by) -> AdminApiKey:
    if key.revoked_at is None:
        key.revoked_at = timezone.now()
        key.revoked_by = by
        key.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    return key


def _refuse(reason: str, **extra) -> AuthenticationFailed:
    logger.info("api_key_refused", extra={"reason": reason, **extra})
    return AuthenticationFailed(
        "This API key is not valid. Create a new one in the admin console.",
        code="api_key_invalid",
    )


def authenticate(request, raw_key: str):
    """(user, key) for a valid key used where keys may be used; raises otherwise."""
    body = raw_key[len(KEY_MARKER):]
    prefix, _, secret = body.partition("_")
    if not prefix or not secret:
        raise _refuse("malformed")

    key = (AdminApiKey.objects.select_related("owner")
           .filter(prefix=prefix).first())
    if key is None or not hmac.compare_digest(key.key_hash, _hash(raw_key)):
        raise _refuse("unknown")

    owner = key.owner
    if key.revoked_at is not None:
        raise _refuse("revoked", key_id=str(key.pk))
    if key.is_expired:
        raise _refuse("expired", key_id=str(key.pk))
    if key.token_version != owner.token_version:
        raise _refuse("owner_signed_out_everywhere", key_id=str(key.pk))
    if not owner.is_active or owner.is_suspended or not owner.is_staff_role:
        raise _refuse("owner_not_staff", key_id=str(key.pk))

    path = request.path
    if not path.startswith(ADMIN_PATH) or path.startswith(KEYS_PATH):
        raise PermissionDenied("API keys only work on the admin API, and cannot manage keys.")
    if key.access != ApiKeyAccess.WRITE and request.method not in SAFE_METHODS:
        raise PermissionDenied("This API key is read only.")

    now = timezone.now()
    if key.last_used_at is None or now - key.last_used_at >= _TOUCH_EVERY:
        from apps.common.middleware import get_client_ip

        ip = get_client_ip(request) or None
        AdminApiKey.objects.filter(pk=key.pk).update(last_used_at=now, last_used_ip=ip)
        key.last_used_at, key.last_used_ip = now, ip
    return owner, key
