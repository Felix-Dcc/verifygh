from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.constants import ROLE_PERMISSIONS, STAFF_ROLES, Role
from apps.accounts.managers import UserManager
from apps.common.models import BaseModel, TimeStampedModel


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """Platform account.

    Email is the login identifier. The phone number is optional at signup - a
    user only needs one when they deposit - but it is normalised to E.164 and
    unique when present, because it is also an abuse signal.
    """

    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True, default="")

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER, db_index=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)

    # Suspension is separate from is_active so support can distinguish
    # "deactivated their own account" from "we stopped them".
    is_suspended = models.BooleanField(default=False, db_index=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True, default="")

    # Acceptable Use Policy gate. Purchases are blocked until the current
    # version is accepted.
    accepted_terms_version = models.CharField(max_length=32, blank=True, default="")
    accepted_terms_at = models.DateTimeField(null=True, blank=True)

    # The Google account this one signs in with (its stable `sub`), once linked.
    # Matched before the email address, which a Google account can change.
    google_subject = models.CharField(max_length=255, blank=True, default="")

    totp_secret = models.CharField(max_length=64, blank=True, default="")
    is_two_factor_enabled = models.BooleanField(default=False)

    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Session epoch. Every token carries this value as a claim, and the auth
    # layer rejects any token whose claim does not match. Bumping it revokes
    # every session instantly - including access tokens already in flight,
    # which blacklisting a refresh token on its own cannot do.
    token_version = models.PositiveIntegerField(default=0)

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    signup_ip = models.GenericIPAddressField(null=True, blank=True)
    risk_score = models.PositiveIntegerField(default=0, db_index=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "accounts_user"
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=~models.Q(phone=""),
                name="user_phone_unique_when_set",
            ),
            models.UniqueConstraint(
                fields=["google_subject"],
                condition=~models.Q(google_subject=""),
                name="user_google_subject_unique_when_set",
            ),
        ]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["role", "is_suspended"]),
        ]

    def __str__(self) -> str:
        return self.email

    # -- roles ------------------------------------------------------------

    @property
    def is_staff_role(self) -> bool:
        return self.role in STAFF_ROLES

    def has_admin_permission(self, permission: str) -> bool:
        return str(permission) in ROLE_PERMISSIONS.get(self.role, set())

    @property
    def admin_permissions(self) -> list[str]:
        return sorted(ROLE_PERMISSIONS.get(self.role, set()))

    # -- gates ------------------------------------------------------------

    @property
    def has_accepted_current_terms(self) -> bool:
        return self.accepted_terms_version == settings.VERIFYGH["CURRENT_TERMS_VERSION"]

    @property
    def is_locked_out(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def register_failed_login(self) -> None:
        limit = settings.VERIFYGH["MAX_FAILED_LOGINS"]
        minutes = settings.VERIFYGH["LOGIN_LOCKOUT_MINUTES"]
        self.failed_login_count += 1
        fields = ["failed_login_count", "updated_at"]
        if self.failed_login_count >= limit:
            self.locked_until = timezone.now() + timedelta(minutes=minutes)
            self.failed_login_count = 0
            fields.append("locked_until")
        self.save(update_fields=fields)

    def revoke_all_sessions(self) -> int:
        """Sign this user out everywhere, immediately.

        Two mechanisms, because they cover different windows:

        * bumping ``token_version`` invalidates every *access* token the moment
          the next request arrives, without waiting for it to expire;
        * blacklisting the outstanding *refresh* tokens means a stolen one
          cannot mint a fresh pair even if the version check were bypassed.

        Returns the number of refresh tokens blacklisted.
        """
        type(self).objects.filter(pk=self.pk).update(
            token_version=models.F("token_version") + 1
        )
        self.refresh_from_db(fields=["token_version"])

        blacklisted = 0
        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                BlacklistedToken,
                OutstandingToken,
            )
        except ImportError:  # blacklist app not installed
            return blacklisted

        for token in OutstandingToken.objects.filter(user=self):
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            blacklisted += int(created)
        return blacklisted

    def register_successful_login(self, ip: str | None = None) -> None:
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login = timezone.now()
        self.last_login_ip = ip or None
        self.save(
            update_fields=[
                "failed_login_count",
                "locked_until",
                "last_login",
                "last_login_ip",
                "updated_at",
            ]
        )


class TokenPurpose(models.TextChoices):
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION", "Email verification"
    PASSWORD_RESET = "PASSWORD_RESET", "Password reset"


class SecurityToken(BaseModel):
    """Single-use, hashed, expiring token for email verification and resets.

    Only the SHA-256 hash is stored, so a database leak does not hand an
    attacker a working password-reset link.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="security_tokens")
    purpose = models.CharField(max_length=32, choices=TokenPurpose.choices, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "accounts_security_token"
        indexes = [models.Index(fields=["user", "purpose", "used_at"])]

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, user: User, purpose: str, ttl_hours: int, ip: str | None = None,
              *, keep_recent: int = 1):
        """Returns (instance, raw_token). The raw token is never stored.

        At most `keep_recent` live tokens per purpose, the new one included:
        issuing invalidates the rest, oldest first. The default, one, means the
        most recent email is the only one that works (password resets).
        Email verification keeps a few: see `send_verification_email`.

        Invalidating and inserting have to happen under a lock, not as two
        independent statements. Without it two overlapping requests - a user
        clicking "resend" twice, or a retry arriving beside the original - would
        each find nothing to invalidate and each insert, leaving two live links
        where the caller was promised one. The lock is taken on the *user* row
        because that is what the two callers have in common; there is no token
        row yet to lock.
        """
        raw = secrets.token_urlsafe(32)
        with transaction.atomic():
            type(user).objects.select_for_update().filter(pk=user.pk).first()
            live = cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True)
            kept = list(live.order_by("-created_at")
                        .values_list("pk", flat=True)[:max(keep_recent - 1, 0)])
            live.exclude(pk__in=kept).update(used_at=timezone.now())
            instance = cls.objects.create(
                user=user,
                purpose=purpose,
                token_hash=cls.hash_token(raw),
                expires_at=timezone.now() + timedelta(hours=ttl_hours),
                requested_ip=ip or None,
            )
        return instance, raw

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    @property
    def is_expired(self) -> bool:
        """Distinguishable from "used" so the UI can say which it was."""
        return self.expires_at <= timezone.now()

    def consume(self) -> bool:
        """Claim this token. Returns False if someone else already claimed it.

        A conditional UPDATE rather than a read-then-save: two requests arriving
        with the same token would both pass an `is_valid` check, and only the
        row-level `used_at IS NULL` filter can decide between them. Exactly one
        caller gets True, which is what makes single-use hold when a mail client
        prefetches the link at the same moment the user clicks it.
        """
        now = timezone.now()
        claimed = type(self).objects.filter(pk=self.pk, used_at__isnull=True).update(
            used_at=now, updated_at=now
        )
        if claimed:
            self.used_at = now
        return bool(claimed)


class LoginAttempt(TimeStampedModel):
    """Authentication telemetry. Feeds the suspicious-activity scorer."""

    email = models.CharField(max_length=254, db_index=True)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_attempts"
    )
    successful = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    failure_reason = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "accounts_login_attempt"
        indexes = [models.Index(fields=["created_at", "successful"])]


class UserDevice(TimeStampedModel):
    """Coarse device fingerprint (user agent + IP) for abuse detection only.

    Deliberately not a tracking identifier: a salted hash is stored, never the
    raw fingerprint, and it is used solely to flag one device driving many
    accounts.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    fingerprint_hash = models.CharField(max_length=64, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    seen_count = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "accounts_user_device"
        constraints = [
            models.UniqueConstraint(fields=["user", "fingerprint_hash"], name="user_device_unique")
        ]

    @staticmethod
    def fingerprint(user_agent: str, ip: str) -> str:
        salt = settings.SECRET_KEY
        return hashlib.sha256(f"{salt}|{user_agent}|{ip}".encode()).hexdigest()
