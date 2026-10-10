"""Account lifecycle: registration, verification, password reset, device tracking."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import (
    EmailVerificationCode,
    LoginAttempt,
    SecurityToken,
    TokenPurpose,
    User,
    UserDevice,
)
from apps.common.errors import Conflict, ValidationFailed
from apps.common.middleware import get_client_ip

logger = logging.getLogger("verifygh.accounts")

#: Subject lines are fixed strings, not derived from user input - and never
#: carry the code: subjects are kept in the notification row and in Brevo's log.
VERIFY_EMAIL_SUBJECT = "Your VerifyGH verification code"

#: The 6-digit code emailed with the link (9 Oct 2026: typed, not clicked).
EMAIL_CODE_TTL_MINUTES = 15
EMAIL_CODE_MAX_ATTEMPTS = 5
#: The least time between two codes for one account.
EMAIL_CODE_RESEND_SECONDS = 45
#: An account this new still has its sign-up email on the way: the app does
#: not send another of its own accord.
EMAIL_CODE_SIGNUP_GRACE_SECONDS = 120
#: How many times a user may correct their own unverified address.
SELF_EMAIL_CHANGES_ALLOWED = 3


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


class GoogleAccountConflict(Exception):
    """The address's VerifyGH account is already linked to a different Google account."""


@transaction.atomic
def sign_in_with_google(*, subject: str, email: str, name: str = "",
                        accepted_terms: bool = False, referral_code: str = "",
                        request=None) -> tuple[User, bool]:
    """The account a verified Google identity signs in to: (user, created).

    In order: the account already linked to this Google account; else the
    account with this email address, which is linked now; else a new account.
    Google has confirmed the address belongs to whoever is signing in (the
    caller checks `email_verified`), so a new account starts verified.

    Linking to an account whose address was never verified also retires its
    password and ends its sessions. Whoever set that password never proved they
    own the address - it could be someone who registered it first to wait for
    the real owner (account pre-hijacking). The owner can set a new password
    with a reset link.
    """
    linked = User.objects.select_for_update().filter(google_subject=subject).first()
    if linked is not None:
        return linked, False

    existing = User.objects.select_for_update().filter(email__iexact=email).first()
    if existing is not None:
        if existing.google_subject and existing.google_subject != subject:
            raise GoogleAccountConflict()
        existing.google_subject = subject
        fields = ["google_subject", "updated_at"]
        retired_password = False
        if not existing.is_email_verified:
            existing.is_email_verified = True
            existing.email_verified_at = timezone.now()
            fields += ["is_email_verified", "email_verified_at"]
            if existing.has_usable_password():
                existing.set_unusable_password()
                fields.append("password")
                retired_password = True
        existing.save(update_fields=fields)
        if retired_password:
            existing.revoke_all_sessions()
        if "is_email_verified" in fields:
            # Newly verified: the usual last gate before a referral qualifies.
            from apps.referrals.services import process_for_user

            process_for_user(existing)
        logger.info(
            "google_account_linked",
            extra={"user_id": str(existing.pk), "password_retired": retired_password},
        )
        return existing, False

    ip = get_client_ip(request) if request else None
    terms = (
        {"accepted_terms_version": settings.VERIFYGH["CURRENT_TERMS_VERSION"],
         "accepted_terms_at": timezone.now()}
        if accepted_terms else {}
    )
    user = User.objects.create_user(
        email=email,
        password=None,
        full_name=name.strip()[:150],
        signup_ip=ip or None,
        is_email_verified=True,
        email_verified_at=timezone.now(),
        google_subject=subject,
        **terms,
    )

    from apps.referrals.services import attach_referral, process_for_user

    attach_referral(new_user=user, raw_code=referral_code, request=request)
    # Verified from the start, so a referral is checked now rather than on a
    # verification email that is never sent.
    process_for_user(user)
    logger.info("user_registered", extra={"user_id": str(user.id), "method": "google"})
    return user, True


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


#: How many of the most recent verification emails still work.
VERIFICATION_LINKS_KEPT = 3


def send_verification_email(user: User, ip: str | None = None) -> bool:
    """Issue a fresh verification code and link, and email both.

    Returns True if the provider accepted the message. The code is what the
    app asks for; the link is the fallback for another device. A new code
    replaces the last one; the last few links stay valid (see below).
    """
    from apps.notifications.models import DeliveryStatus
    from apps.notifications.services import notify

    if user.is_email_verified:
        return False

    hours = _email_ttl_hours()
    # The last few links stay valid, not only the newest. Every one went to
    # this inbox, so any of them proves the address; and Gmail threads emails
    # with one subject, so customers who asked again tapped an older message's
    # button and were told it was invalid (9 Oct 2026). Capped, so old emails
    # are not a drawer of live keys; changing the address cancels them all.
    _token, raw = SecurityToken.issue(
        user, TokenPurpose.EMAIL_VERIFICATION, hours, ip,
        keep_recent=VERIFICATION_LINKS_KEPT,
    )
    _code, raw_code = EmailVerificationCode.issue(user, EMAIL_CODE_TTL_MINUTES)
    # Re-read after issuing: `issue` locks the user row, so this is the address
    # as of this token. A task that loaded the user before staff corrected the
    # address must not mail a live link to the old one.
    user.refresh_from_db(fields=["email", "is_email_verified"])
    if user.is_email_verified:
        return False
    # The raw token and code appear in the email body and nowhere else - never
    # in a log line, the subject, or the notification body stored in the
    # database.
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
            "code": raw_code,
            "code_minutes": EMAIL_CODE_TTL_MINUTES,
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


EMAIL_ALREADY_VERIFIED = (
    "This email has already been verified. Email changes are restricted to unverified accounts."
)


def _readdress(target: User, new_email: str) -> int:
    """Move a locked, unverified account to `new_email`; returns links cancelled.

    Every unused link and code goes: one mailed to the wrong address would
    otherwise verify the new one, or reset the password, for whoever owns it.
    """
    now = timezone.now()
    cancelled = SecurityToken.objects.filter(
        user=target, used_at__isnull=True,
        purpose__in=[TokenPurpose.EMAIL_VERIFICATION, TokenPurpose.PASSWORD_RESET],
    ).update(used_at=now)
    EmailVerificationCode.objects.filter(user=target, used_at__isnull=True).update(used_at=now)

    target.email = new_email
    target.is_email_verified = False
    target.email_verified_at = None
    try:
        # A savepoint, so a lost race on the unique email leaves the outer
        # transaction usable for the clean error below.
        with transaction.atomic():
            target.save(update_fields=["email", "is_email_verified",
                                       "email_verified_at", "updated_at"])
    except IntegrityError:
        raise Conflict("Another account already uses this email.",
                       code="EMAIL_TAKEN") from None
    return cancelled


def change_own_unverified_email(*, user: User, new_email: str, password: str,
                                request=None) -> User:
    """The customer corrects their own mistyped address, before verifying.

    Only while unverified - a verified address is proven, and replacing it
    would be account takeover - and only with the account password, a few
    times per account. The session stays (the password was just proven); every
    old link and code is cancelled and a new code goes to the new address.
    """
    from apps.audit.models import AuditLog
    from apps.audit.services import record_audit

    new_email = (new_email or "").strip().lower()
    with transaction.atomic():
        target = User.objects.select_for_update().get(pk=user.pk)
        if target.is_email_verified:
            raise Conflict(EMAIL_ALREADY_VERIFIED, code="EMAIL_ALREADY_VERIFIED")
        if not password or not target.check_password(password):
            raise ValidationFailed(
                "That password isn't right.",
                details={"fields": {"password": ["That password isn't right."]}},
                code="INVALID_PASSWORD")
        previous = target.email
        if new_email == previous.lower():
            raise ValidationFailed(
                "That's the address you already have.",
                details={"fields": {"new_email": ["Same as the current email."]}},
            )
        used = AuditLog.objects.filter(actor=target, action="EMAIL_SELF_CHANGED").count()
        if used >= SELF_EMAIL_CHANGES_ALLOWED:
            raise Conflict("You've already changed your address the most times allowed. "
                           "Contact support to change it again.", code="EMAIL_CHANGE_LIMIT")
        if User.objects.filter(email__iexact=new_email).exclude(pk=target.pk).exists():
            raise Conflict("Another account already uses this email.", code="EMAIL_TAKEN")

        _readdress(target, new_email)
        record_audit(actor=target, action="EMAIL_SELF_CHANGED", target=target, request=request,
                     metadata={"from": previous, "to": new_email})

    logger.info("user_changed_unverified_email", extra={"user_id": str(target.pk)})
    target.refresh_from_db()
    # Sent now, not queued: the verify screen asks for this code next.
    try:
        send_verification_email(target, ip=get_client_ip(request) if request else None)
    except Exception:
        logger.error("verification_email_failed", extra={"user_id": str(target.pk)},
                     exc_info=True)
    return target


def admin_change_unverified_email(*, user: User, new_email: str, reason: str, actor,
                                  request=None) -> User:
    """Staff correct an address the user mistyped at registration.

    Only while that address is unverified: a verified address is proven to be
    the user's, and replacing it is account takeover, not a correction. The new
    address starts unverified too - staff only know what the user told them.

    Tokens belong to the account, not to an address, so every unused
    verification and password-reset link is cancelled: one already mailed to
    the wrong address would otherwise verify the new one, or reset the
    password, for whoever owns the wrong address. Sessions end for the same
    reason; the user signs in again with their password. A fresh link goes to
    the new address once this commits.
    """
    from apps.audit.services import record_admin_action

    new_email = (new_email or "").strip().lower()
    with transaction.atomic():
        # Locked, then re-checked: the user may verify the old address, or
        # someone may register the new one, while staff fill in the form.
        target = User.objects.select_for_update().get(pk=user.pk)
        if target.is_email_verified:
            raise Conflict(EMAIL_ALREADY_VERIFIED, code="EMAIL_ALREADY_VERIFIED")
        previous = target.email
        if new_email == previous.lower():
            raise ValidationFailed(
                "The new email is the same as the current one.",
                details={"fields": {"new_email": ["Same as the current email."]}},
            )
        if User.objects.filter(email__iexact=new_email).exclude(pk=target.pk).exists():
            raise Conflict("Another account already uses this email.", code="EMAIL_TAKEN")

        cancelled = _readdress(target, new_email)

        record_admin_action(
            admin=actor, action="ADMIN_CHANGED_UNVERIFIED_EMAIL", target=target,
            reason=reason, before={"email": previous, "is_email_verified": False},
            after={"email": new_email, "is_email_verified": False,
                   "links_cancelled": cancelled},
            request=request,
        )
        target.revoke_all_sessions()

        ip = get_client_ip(request) if request else None
        transaction.on_commit(lambda: dispatch_verification_email(target, ip=ip))

    logger.info("admin_changed_unverified_email", extra={
        "user_id": str(target.pk), "admin_id": str(getattr(actor, "pk", "")),
        "from": mask_email(previous), "to": mask_email(new_email),
    })
    return target


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
        newly = _mark_verified(user)

    if newly:
        _after_verified(user, method="link")
    user.refresh_from_db()
    return user


def _mark_verified(user: User) -> bool:
    """Mark the address verified and retire every other link and code.

    Inside the caller's transaction. A conditional update, so a code and a
    link arriving together verify the account once: True for the one that did.
    """
    now = timezone.now()
    newly = bool(User.objects.filter(pk=user.pk, is_email_verified=False).update(
        is_email_verified=True, email_verified_at=now, updated_at=now))
    # Their job is done: the other links and codes still in the inbox retire.
    SecurityToken.objects.filter(
        user=user, purpose=TokenPurpose.EMAIL_VERIFICATION, used_at__isnull=True,
    ).update(used_at=now)
    EmailVerificationCode.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    return newly


def _after_verified(user: User, *, method: str) -> None:
    logger.info("email_verified", extra={"user_id": str(user.id), "method": method})
    # Verification is the usual last gate before a referral becomes eligible.
    from apps.referrals.services import process_for_user

    process_for_user(user)


def verify_email_code(user: User, code: str) -> User:
    """Check a typed 6-digit code; verify the account when it matches.

    `INVALID_CODE` says how many tries are left; after
    EMAIL_CODE_MAX_ATTEMPTS wrong ones the code is dead and `CODE_EXPIRED`
    asks for a new one. The code is compared in constant time against its
    keyed hash and never logged.
    """
    typed = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(typed) != 6:
        raise ValidationFailed("Enter the 6-digit code from the email.", code="INVALID_CODE")

    wrong_left = None
    with transaction.atomic():
        account = User.objects.select_for_update().get(pk=user.pk)
        if account.is_email_verified:
            return account
        row = (EmailVerificationCode.objects.select_for_update()
               .filter(user=account, used_at__isnull=True).order_by("-created_at").first())
        if row is None or row.expires_at <= timezone.now() \
                or row.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
            raise ValidationFailed("This code has expired. Send yourself a new one.",
                                   code="CODE_EXPIRED")
        import hmac

        if hmac.compare_digest(row.code_hash,
                               EmailVerificationCode.hash_code(account.pk, typed)):
            row.used_at = timezone.now()
            row.save(update_fields=["used_at", "updated_at"])
            newly = _mark_verified(account)
        else:
            # Counted before the refusal, and committed with it.
            row.attempts += 1
            fields = ["attempts", "updated_at"]
            if row.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
                row.used_at = timezone.now()
                fields.append("used_at")
            row.save(update_fields=fields)
            wrong_left = EMAIL_CODE_MAX_ATTEMPTS - row.attempts

    if wrong_left is not None:
        logger.info("email_code_wrong", extra={"user_id": str(user.id),
                                               "tries_left": wrong_left})
        if wrong_left <= 0:
            raise ValidationFailed("Too many wrong tries. Send yourself a new code.",
                                   code="CODE_EXPIRED")
        raise ValidationFailed(
            f"That code isn't right. {wrong_left} {'try' if wrong_left == 1 else 'tries'} left.",
            code="INVALID_CODE")
    if newly:
        _after_verified(user, method="code")
    user.refresh_from_db()
    return user


def verification_status(user: User) -> dict:
    """What the verify screen needs: is a code on its way, when may it resend."""
    now = timezone.now()
    latest = EmailVerificationCode.objects.filter(user=user).order_by("-created_at").first()
    since = (now - latest.created_at).total_seconds() if latest else None
    live = bool(latest and latest.used_at is None and latest.expires_at > now
                and latest.attempts < EMAIL_CODE_MAX_ATTEMPTS)
    # A brand-new account's sign-up email may still be on its way.
    fresh = (now - user.created_at).total_seconds() < EMAIL_CODE_SIGNUP_GRACE_SECONDS
    resend_in = max(0, int(EMAIL_CODE_RESEND_SECONDS - since)) if since is not None else 0
    if latest is None and fresh:
        resend_in = max(0, int(EMAIL_CODE_RESEND_SECONDS
                               - (now - user.created_at).total_seconds()))
    return {"verified": user.is_email_verified, "email": user.email,
            "code_active": live or (latest is None and fresh), "resend_in": resend_in}


def send_verification_code(user: User, ip: str | None = None) -> dict:
    """Send a new code (and link) unless one went out a moment ago."""
    status = verification_status(user)
    if user.is_email_verified:
        return {**status, "sent": False}
    if status["resend_in"] > 0:
        return {**status, "sent": False}
    delivered = send_verification_email(user, ip=ip)
    return {**verification_status(user), "sent": True, "delivered": delivered}


def verified_owner(raw_token: str) -> User | None:
    """The account a verification link belongs to, if it is already verified.

    A link opened a second time - on another device, by a mail scanner, or
    after another email's link - would otherwise say "invalid" to someone
    whose address is verified. Reveals nothing a guesser could use: it needs
    the token itself, which only the inbox has.
    """
    token = SecurityToken.objects.filter(
        token_hash=SecurityToken.hash_token(raw_token),
        purpose=TokenPurpose.EMAIL_VERIFICATION,
    ).select_related("user").first()
    if token is None or not token.user.is_email_verified:
        return None
    return token.user


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
    # The address as of this token (see send_verification_email): never a live
    # reset link to an address staff have just corrected away from.
    user.refresh_from_db(fields=["email"])
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
