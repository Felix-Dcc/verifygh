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
