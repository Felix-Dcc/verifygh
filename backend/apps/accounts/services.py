"""Account lifecycle: registration, verification, password reset, device tracking."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import LoginAttempt, SecurityToken, TokenPurpose, User, UserDevice
from apps.common.errors import ValidationFailed
from apps.common.middleware import get_client_ip

logger = logging.getLogger("verifygh.accounts")

EMAIL_TOKEN_TTL_HOURS = 48
RESET_TOKEN_TTL_HOURS = 2


def _frontend(path: str) -> str:
    base = str(settings.VERIFYGH["FRONTEND_URL"]).rstrip("/")
    return f"{base}{path}"


@transaction.atomic
def register_user(*, email: str, password: str, full_name: str = "", phone: str = "",
                  accepted_terms: bool = False, referral_code: str = "", request=None) -> User:
    """Create an account. The wallet is created by a post_save signal."""
    if not accepted_terms:
        raise ValidationFailed(
            "You must accept the Terms and Acceptable Use Policy to create an account.",
            details={"fields": {"accepted_terms": ["Required."]}},
        )

    ip = get_client_ip(request) if request else None
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name.strip(),
        phone=phone or "",
        signup_ip=ip or None,
        accepted_terms_version=settings.VERIFYGH["CURRENT_TERMS_VERSION"],
        accepted_terms_at=timezone.now(),
    )

    if request is not None:
        track_device(user, request)

    # Attribution happens here, once, from the code the backend resolves - not
    # from anything the browser claims later. An unknown code is ignored and
    # registration continues.
    from apps.referrals.services import attach_referral

    attach_referral(new_user=user, raw_code=referral_code, request=request)

    transaction.on_commit(lambda: send_verification_email(user, ip=ip))
    logger.info("user_registered", extra={"user_id": str(user.id)})
    return user


def send_verification_email(user: User, ip: str | None = None) -> None:
    from apps.notifications.services import notify

    if user.is_email_verified:
        return
    _token, raw = SecurityToken.issue(
        user, TokenPurpose.EMAIL_VERIFICATION, EMAIL_TOKEN_TTL_HOURS, ip
    )
    notify(
        user,
        event="ACCOUNT_CREATED",
        title="Confirm your email address",
        body="Welcome to VerifyGH. Confirm your email address to start using your wallet.",
        email_template="emails/verify_email.txt",
        context={
            "full_name": user.full_name or "there",
            "verify_url": _frontend(f"/verify-email?token={raw}"),
            "hours": EMAIL_TOKEN_TTL_HOURS,
        },
        channels=("EMAIL",),
    )


def verify_email(raw_token: str) -> User:
    token = SecurityToken.objects.filter(
        token_hash=SecurityToken.hash_token(raw_token),
        purpose=TokenPurpose.EMAIL_VERIFICATION,
    ).select_related("user").first()

    if token is None or not token.is_valid:
        raise ValidationFailed(
            "This verification link is invalid or has expired. Request a new one.",
            code="INVALID_TOKEN",
        )

    with transaction.atomic():
        token.consume()
        user = token.user
        user.is_email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=["is_email_verified", "email_verified_at", "updated_at"])

    logger.info("email_verified", extra={"user_id": str(user.id)})

    # Verification is the usual last gate before a referral becomes eligible.
    from apps.referrals.services import process_for_user

    process_for_user(user)
    return user


def request_password_reset(email: str, request=None) -> None:
    """Always returns quietly.

    Whether the address exists is not disclosed - that would turn this endpoint
    into an account-enumeration oracle.
    """
    from apps.notifications.services import notify

    user = User.objects.filter(email__iexact=email.strip()).first()
    if user is None or not user.is_active:
        logger.info("password_reset_unknown_email")
        return

    ip = get_client_ip(request) if request else None
    _token, raw = SecurityToken.issue(user, TokenPurpose.PASSWORD_RESET, RESET_TOKEN_TTL_HOURS, ip)
    notify(
        user,
        event="SECURITY_ALERT",
        title="Reset your password",
        body="We received a request to reset your VerifyGH password.",
        email_template="emails/password_reset.txt",
        context={
            "full_name": user.full_name or "there",
            "reset_url": _frontend(f"/reset-password?token={raw}"),
            "hours": RESET_TOKEN_TTL_HOURS,
        },
        channels=("EMAIL",),
    )


def reset_password(raw_token: str, new_password: str) -> User:
    from django.contrib.auth.password_validation import validate_password

    token = SecurityToken.objects.filter(
        token_hash=SecurityToken.hash_token(raw_token),
        purpose=TokenPurpose.PASSWORD_RESET,
    ).select_related("user").first()

    if token is None or not token.is_valid:
        raise ValidationFailed(
            "This reset link is invalid or has expired. Request a new one.",
            code="INVALID_TOKEN",
        )

    user = token.user
    validate_password(new_password, user)

    with transaction.atomic():
        token.consume()
        user.set_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["password", "failed_login_count", "locked_until", "updated_at"])

        # A reset is usually the response to a compromise, so every session the
        # attacker may hold has to end here - not when their access token
        # happens to expire.
        revoked = user.revoke_all_sessions()
        logger.info(
            "sessions_revoked",
            extra={"user_id": str(user.id), "reason": "password_reset", "tokens": revoked},
        )

    from apps.notifications.services import notify

    notify(
        user,
        event="SECURITY_ALERT",
        title="Your password was changed",
        body="Your VerifyGH password was changed. If this was not you, contact support now.",
        channels=("EMAIL", "IN_APP"),
    )
    logger.info("password_reset_completed", extra={"user_id": str(user.id)})
    return user


def record_login_attempt(*, email: str, user: User | None, successful: bool,
                         request=None, reason: str = "") -> None:
    LoginAttempt.objects.create(
        email=(email or "")[:254].lower(),
        user=user,
        successful=successful,
        ip_address=(get_client_ip(request) if request else None) or None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        failure_reason=reason[:64],
    )


def track_device(user: User, request) -> None:
    """Record the device fingerprint, and flag shared devices for review."""
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
    ip = get_client_ip(request)
    fingerprint = UserDevice.fingerprint(user_agent, ip)

    device, created = UserDevice.objects.get_or_create(
        user=user,
        fingerprint_hash=fingerprint,
        defaults={"last_ip": ip or None},
    )
    if not created:
        UserDevice.objects.filter(pk=device.pk).update(
            last_seen_at=timezone.now(),
            last_ip=ip or None,
            seen_count=device.seen_count + 1,
        )

    from apps.audit.services import evaluate_device_sharing

    evaluate_device_sharing(user=user, fingerprint_hash=fingerprint, ip=ip)
