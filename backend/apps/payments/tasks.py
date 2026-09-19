from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import reconcile_payment

logger = logging.getLogger("verifygh.payments")


@shared_task(name="apps.payments.tasks.expire_stale_payments")
def expire_stale_payments() -> dict:
    """Close out prompts the user never approved - but ask the provider first.

    Marking a payment EXPIRED without checking would be how a real deposit gets
    lost: the user approved late, the webhook was dropped, and we wrote off a
    payment the provider actually collected.
    """
    now = timezone.now()
    stale = Payment.objects.filter(
        status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING],
        expires_at__lt=now,
    )[:200]

    expired = 0
    recovered = 0

    for payment in stale:
        refreshed = reconcile_payment(payment)
        if refreshed.status == PaymentStatus.SUCCESS:
            recovered += 1
            continue
        if refreshed.status in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
            Payment.objects.filter(pk=payment.pk, credited_at__isnull=True).update(
                status=PaymentStatus.EXPIRED,
                failure_reason="The payment prompt expired before it was approved.",
                completed_at=now,
            )
            expired += 1

    if expired or recovered:
        logger.info("payments_expiry_sweep", extra={"expired": expired, "recovered": recovered})
    return {"expired": expired, "recovered": recovered}


@shared_task(name="apps.payments.tasks.reconcile_recent_payments")
def reconcile_recent_payments(minutes: int = 120) -> dict:
    """Catch payments whose webhook never arrived."""
    since = timezone.now() - timedelta(minutes=minutes)
    pending = Payment.objects.filter(
        status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING],
        created_at__gte=since,
    )[:200]

    checked = 0
    credited = 0
    for payment in pending:
        checked += 1
        if reconcile_payment(payment).status == PaymentStatus.SUCCESS:
            credited += 1

    logger.info("payments_reconciled", extra={"checked": checked, "credited": credited})
    return {"checked": checked, "credited": credited}


@shared_task(name="apps.payments.tasks.retry_failed_webhooks")
def retry_failed_webhooks(limit: int = 100) -> dict:
    """Finish applying verified callbacks that were recorded but never applied.

    This is the safety net behind the safety net. A provider retries a handful
    of times and then gives up; without this, a transient database error during
    one webhook would leave a customer permanently uncredited.
    """
    from apps.payments.models import PaymentWebhookEvent
    from apps.payments.services import UNPARSED_EVENT_TYPE, replay_failed_webhook

    stuck = (
        PaymentWebhookEvent.objects.filter(processed=False, signature_valid=True)
        .exclude(event_type=UNPARSED_EVENT_TYPE)  # needs a human, not a retry
        .order_by("created_at")[:limit]
    )

    replayed = 0
    failed = 0
    for record in stuck:
        if replay_failed_webhook(record):
            replayed += 1
        else:
            failed += 1

    if replayed or failed:
        logger.warning(
            "failed_webhooks_swept", extra={"replayed": replayed, "still_failing": failed}
        )
    return {"replayed": replayed, "still_failing": failed}
