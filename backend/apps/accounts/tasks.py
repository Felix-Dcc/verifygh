from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("verifygh.accounts")


@shared_task(name="apps.accounts.tasks.flush_expired_tokens")
def flush_expired_tokens() -> dict:
    """Drop blacklist rows for tokens that have expired anyway.

    Without this the outstanding/blacklist tables grow with every sign-in and
    every refresh, forever. An expired token is already refused on its `exp`
    claim, so keeping a blacklist row for it buys nothing.
    """
    from django.utils import timezone

    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:
        return {"deleted": 0}

    now = timezone.now()
    blacklisted, _ = BlacklistedToken.objects.filter(token__expires_at__lte=now).delete()
    outstanding, _ = OutstandingToken.objects.filter(expires_at__lte=now).delete()

    logger.info(
        "expired_tokens_flushed",
        extra={"blacklisted": blacklisted, "outstanding": outstanding},
    )
    return {"blacklisted": blacklisted, "outstanding": outstanding}


@shared_task(name="apps.accounts.tasks.prune_login_attempts")
def prune_login_attempts(days: int = 365) -> dict:
    """Delete authentication telemetry past its retention window.

    The Privacy Policy commits to roughly 12 months for security records, so
    this is the code that makes that statement true rather than aspirational.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.accounts.models import LoginAttempt

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = LoginAttempt.objects.filter(created_at__lt=cutoff).delete()
    logger.info("login_attempts_pruned", extra={"deleted": deleted, "days": days})
    return {"deleted": deleted}


@shared_task(
    name="apps.accounts.tasks.send_verification_email",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    # A retry storm against the mail provider helps nobody, so back off.
    retry_backoff=True,
    retry_jitter=True,
)
def send_verification_email_task(self, user_id: str, ip: str = "") -> dict:
    """Send the verification email off the request thread.

    Retried a few times because "the mail provider had a bad minute" is the
    common case and it is invisible to the user, who is left waiting for an
    email that will never come. After the retries are exhausted it gives up
    quietly: the account exists and unverified, and the user can ask for
    another link.
    """
    from apps.accounts.models import User
    from apps.accounts.services import send_verification_email

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        logger.warning("verification_email_user_missing", extra={"user_id": str(user_id)})
        return {"sent": False, "reason": "user_missing"}

    if user.is_email_verified:
        return {"sent": False, "reason": "already_verified"}

    try:
        sent = send_verification_email(user, ip=ip or None)
    except Exception as exc:
        logger.warning(
            "verification_email_task_failed",
            extra={"user_id": str(user_id), "error": exc.__class__.__name__},
        )
        raise self.retry(exc=exc) from exc

    if not sent:
        # notify() records the provider failure on the Notification row rather
        # than raising, so an undelivered message reaches us as False.
        logger.warning("verification_email_not_delivered", extra={"user_id": str(user_id)})

    return {"sent": bool(sent)}
