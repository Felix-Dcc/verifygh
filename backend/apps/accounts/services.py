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

#: Subject lines are fixed strings, not derived from user input.
VERIFY_EMAIL_SUBJECT = "Verify your VerifyGH email address"


def _email_ttl_hours() -> int:
    return int(settings.VERIFYGH["EMAIL_VERIFICATION_TTL_HOURS"])


def _reset_ttl_hours() -> int:
    return int(settings.VERIFYGH["PASSWORD_RESET_TTL_HOURS"])


def _frontend(path: str) -> str:
    base = str(settings.VERIFYGH["FRONTEND_URL"]).rstrip("/")
    return f"{base}{path}"


def mask_email(address: str) -> str:
    """`felix@gmail.com` -> `f****@gmail.com`.

    Enough for someone to recognise their own address on the "check your email"
    screen, not enough to hand a stranger a full address they did not know.
    """
    address = (address or "").strip()
    if "@" not in address:
        return ""
    local, _, domain = address.partition("@")
    if not local:
        return f"@{domain}"
    return f"{local[0]}{'*' * max(len(local) - 1, 3)}@{domain}"


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

    # After commit, so the token row the email links to is definitely visible
    # to whoever follows the link - including a worker on another connection.
    transaction.on_commit(lambda: dispatch_verification_email(user, ip=ip))
    logger.info("user_registered", extra={"user_id": str(user.id)})
    return user


def dispatch_verification_email(user: User, ip: str | None = None) -> None:
    """Queue the verification email, falling back to sending it inline.

    Handing this to Celery keeps an unreachable mail server from holding the
    registration response open for the SMTP timeout. If the broker itself is
    unreachable we send inline instead: slower, but the alternative is an
    account nobody can ever verify.
    """
    from apps.accounts.tasks import send_verification_email_task

    try:
        send_verification_email_task.delay(str(user.pk), ip or "")
    except Exception:
        logger.warning(
            "verification_email_enqueue_failed",
            extra={"user_id": str(user.pk)},
            exc_info=True,
        )
        try:
            send_verification_email(user, ip=ip)
        except Exception:
            # Registration has already committed. Losing the email is
            # recoverable - the user can ask for another - so it must not turn
            # a created account into a 500.
            logger.error(
                "verification_email_failed", extra={"user_id": str(user.pk)}, exc_info=True
            )


def send_verification_email(user: User, ip: str | None = None) -> bool:
    """Issue a fresh verification token and email the link.

    Returns True if the provider accepted the message. Issuing a new token
    invalidates any previous one (see `SecurityToken.issue`), so the most recent
    email is always the one that works and an older link cannot be replayed.
    """
    from apps.notifications.models import DeliveryStatus
    from apps.notifications.services import notify

    if user.is_email_verified:
        return False

    hours = _email_ttl_hours()
    _token, raw = SecurityToken.issue(
        user, TokenPurpose.EMAIL_VERIFICATION, hours, ip
    )
    # The raw token appears in the URL and nowhere else - never in a log line,
    # never in the notification body stored in the database.
    sent = notify(
        user,
        event="ACCOUNT_CREATED",
        title="Confirm your email address",
        subject=VERIFY_EMAIL_SUBJECT,
        body="Welcome to VerifyGH. Confirm your email address to start using your wallet.",
        email_template="emails/verify_email.txt",
        context={
            "full_name": user.full_name or "there",
            "verify_url": _frontend(f"/verify-email/{raw}"),
            "hours": hours,
        },
        channels=("EMAIL",),
    )
    delivered = any(n.delivery_status == DeliveryStatus.SENT for n in sent)
    logger.info(
        "verification_email_dispatched",
        extra={"user_id": str(user.id), "delivered": delivered, "ttl_hours": hours},
    )
    return delivered


def resend_verification_email(email: str, request=None) -> None:
    """Public resend. Always returns quietly.

    Deliberately says nothing about whether the address has an account or
    whether it still needs verifying: a caller who could tell the difference
    would have an account-enumeration oracle, and this endpoint is reachable
    without signing in.
    """
    user = User.objects.filter(email__iexact=(email or "").strip()).first()

    if user is None or not user.is_active or user.is_suspended or user.is_email_verified:
        logger.info("verification_resend_ignored")
        return

    ip = get_client_ip(request) if request else None
    # Queued, not sent inline. This endpoint is unauthenticated and its answer
    # is deliberately the same whatever the address is, so there is nothing
    # honest to report back anyway - and sending here would hold a web worker
    # for the SMTP timeout on every call, which is exactly the shape of request
    # you do not want an anonymous caller able to make.
    dispatch_verification_email(user, ip=ip)


def verify_email(raw_token: str) -> User:
    """Consume a verification token and mark the address verified.

    The two failure modes are reported separately - `TOKEN_EXPIRED` and
    `INVALID_TOKEN` - because the frontend shows different copy for each, and
    neither reveals anything about the account: an attacker guessing tokens
    learns only that their guess was not a live token.
    """
    token = SecurityToken.objects.filter(
        token_hash=SecurityToken.hash_token(raw_token),
        purpose=TokenPurpose.EMAIL_VERIFICATION,
    ).select_related("user").first()

    if token is None:
        raise ValidationFailed(
            "This verification link is invalid or has already been used. Request a new one.",
            code="INVALID_TOKEN",
        )

    if token.used_at is None and token.is_expired:
        raise ValidationFailed(
            "This verification link has expired. Request a new one.",
            code="TOKEN_EXPIRED",
        )

    with transaction.atomic():
        # Whoever wins the conditional update does the verification; a second
        # request carrying the same token is told the link is spent.
        if not token.consume():
            raise ValidationFailed(
                "This verification link is invalid or has already been used. "
                "Request a new one.",
                code="INVALID_TOKEN",
            )
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
    hours = _reset_ttl_hours()
    _token, raw = SecurityToken.issue(user, TokenPurpose.PASSWORD_RESET, hours, ip)
    notify(
        user,
        event="SECURITY_ALERT",
        title="Reset your password",
        body="We received a request to reset your VerifyGH password.",
        email_template="emails/password_reset.txt",
        context={
            "full_name": user.full_name or "there",
            "reset_url": _frontend(f"/reset-password?token={raw}"),
            "hours": hours,
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
        if not token.consume():
            raise ValidationFailed(
                "This reset link is invalid or has expired. Request a new one.",
                code="INVALID_TOKEN",
            )
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


def password_candidates(raw: str) -> list[str]:
    """The forms of a submitted password worth checking, most exact first.

    Surrounding whitespace in a password is not significant here, and this is
    where that policy is written down, because for a long time it was only
    half-applied. Registration, password reset and password change all stripped
    it - DRF's CharField trims by default - while login and the current-password
    check were declared `trim_whitespace=False` and did not. A password pasted
    from a note or a message usually carries a trailing space or newline, so its
    owner could create an account and then never sign in with the very password
    they had just chosen. Resetting it repeated the same mismatch on the new
    password, which is why a reset never helped.

    The exact string is still tried first, so an account whose stored password
    really does contain surrounding whitespace - one set from the shell or with
    createsuperuser, which do not strip - keeps working.
    """
    candidates = [raw]
    stripped = raw.strip()
    if stripped and stripped != raw:
        candidates.append(stripped)
    return candidates
