"""Rental housekeeping: confirm purchases, read inboxes, remind, close, purge.

Every provider call here is bounded per run, so our call rate to the provider
stays predictable however many rentals are open; the rate limiter in
apps/verification/registry.py sits underneath as well.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from apps.rentals import services
from apps.rentals.models import ExtensionStatus, Rental, RentalExtension, RentalStatus

logger = logging.getLogger("verifygh.rentals")

#: Rentals one sweep touches upstream, per kind of work.
BATCH_SIZE = 30

#: A purchase is left to its own task for this long before the sweep follows it up.
PENDING_SETTLE_SECONDS = 20


@shared_task(name="apps.rentals.tasks.fulfil_rental", bind=True, max_retries=3,
             default_retry_delay=5, acks_late=True)
def fulfil_rental_task(self, rental_id: str):
    rental = Rental.objects.select_related("provider", "service", "user").filter(
        pk=rental_id).first()
    if rental is None:
        logger.error("fulfil_rental_missing", extra={"rental_id": rental_id})
        return None
    try:
        return services.fulfil_rental(rental).status
    except Exception as exc:
        # Unexpected only: a provider refusal has already been refunded, and an
        # unclear answer is followed up by the sweep with the same key.
        logger.exception("fulfil_rental_unexpected_error", extra={"rental": rental.reference})
        raise self.retry(exc=exc) from exc


@shared_task(name="apps.rentals.tasks.sync_rental_messages")
def sync_rental_messages_task(rental_id: str):
    rental = Rental.objects.select_related("provider", "service", "user").filter(
        pk=rental_id).first()
    if rental is None:
        return 0
    return services.sync_messages(rental)


@shared_task(name="apps.rentals.tasks.process_rentals")
def process_rentals() -> dict:
    """Follow up purchases and extensions, close rentals that ended, send reminders."""
    now = timezone.now()
    give_up_at = now - timedelta(minutes=int(settings.VERIFYGH["RENTAL_PENDING_GIVE_UP_MINUTES"]))
    counts = {"pending": 0, "extensions": 0, "expired": 0, "reminded": 0}
    related = ("provider", "service", "user")

    pending = Rental.objects.select_related(*related).filter(
        status=RentalStatus.PENDING,
        created_at__lt=now - timedelta(seconds=PENDING_SETTLE_SECONDS),
    ).order_by("created_at")[:BATCH_SIZE]
    for rental in pending:
        try:
            services.fulfil_rental(rental, give_up=rental.created_at < give_up_at)
            counts["pending"] += 1
        except Exception:
            logger.exception("rental_followup_failed", extra={"rental": rental.reference})

    extensions = RentalExtension.objects.select_related(
        "rental", "rental__provider", "rental__service", "rental__user").filter(
        status=ExtensionStatus.PENDING,
        created_at__lt=now - timedelta(seconds=PENDING_SETTLE_SECONDS),
    ).order_by("created_at")[:BATCH_SIZE]
    for extension in extensions:
        try:
            services.settle_extension(extension, give_up=extension.created_at < give_up_at)
            counts["extensions"] += 1
        except Exception:
            logger.exception("rental_extension_followup_failed",
                             extra={"rental": extension.rental.reference})

    ended = Rental.objects.select_related(*related).filter(
        status=RentalStatus.ACTIVE, ends_at__lte=now,
    ).order_by("ends_at")[:BATCH_SIZE]
    for rental in ended:
        try:
            if rental.extensions.filter(status=ExtensionStatus.PENDING).exists():
                continue  # settled above first; its new end date decides
            rental = services.refresh_rental(rental)
            if rental.status == RentalStatus.ACTIVE and rental.ends_at and \
                    rental.ends_at <= now - services.EXPIRY_GRACE:
                rental = services.expire_rental(rental)
            if rental.status == RentalStatus.EXPIRED:
                counts["expired"] += 1
        except Exception:
            logger.exception("rental_expiry_failed", extra={"rental": rental.reference})

    counts["reminded"] = _send_reminders(now)
    if any(counts.values()):
        logger.info("rentals_swept", extra=counts)
    return counts


def _send_reminders(now) -> int:
    """One reminder per period: a day before the end (a quarter of a short one)."""
    from apps.notifications.services import notify

    due = Rental.objects.select_related("provider", "service", "user").filter(
        status=RentalStatus.ACTIVE, expiry_notified_at__isnull=True,
        ends_at__gt=now, ends_at__lte=now + timedelta(days=1),
    )[:BATCH_SIZE]
    sent = 0
    for rental in due:
        remaining = rental.ends_at - now
        if remaining > timedelta(days=rental.days) / 4 and rental.days < 4:
            continue  # a short rental is reminded later in its period
        if Rental.objects.filter(pk=rental.pk, expiry_notified_at__isnull=True).update(
                expiry_notified_at=now) != 1:
            continue
        hours = max(1, int(remaining.total_seconds() // 3600))
        notify(rental.user, event="RENTAL_ENDING", title="Your rented number ends soon",
               body=(f"{rental.service_label} number {rental.phone_number} stops receiving "
                     f"messages in about {hours} hour{'s' if hours != 1 else ''}. "
                     "Extend it from the rental's page if you still need it."),
               channels=("IN_APP", "EMAIL"), metadata={"rental_reference": rental.reference})
        sent += 1
    return sent


@shared_task(name="apps.rentals.tasks.poll_rental_messages")
def poll_rental_messages() -> dict:
    """Read the inboxes of active rentals not read within RENTAL_SMS_POLL_SECONDS."""
    now = timezone.now()
    stale_before = now - timedelta(seconds=int(settings.VERIFYGH["RENTAL_SMS_POLL_SECONDS"]))
    due = (Rental.objects.select_related("provider", "service", "user")
           .filter(status=RentalStatus.ACTIVE, ends_at__gt=now)
           .exclude(provider_rental_id="")
           .filter(Q(messages_checked_at__isnull=True) | Q(messages_checked_at__lt=stale_before))
           .order_by(F("messages_checked_at").asc(nulls_first=True))[:BATCH_SIZE])
    polled = new = 0
    for rental in due:
        try:
            new += services.sync_messages(rental)
            polled += 1
        except Exception:
            logger.exception("rental_poll_failed", extra={"rental": rental.reference})
    if new:
        logger.info("rental_inboxes_polled", extra={"polled": polled, "new": new})
    return {"polled": polled, "new": new}


@shared_task(name="apps.rentals.tasks.purge_rental_messages")
def purge_rental_messages(days: int | None = None) -> int:
    """Erase message text and codes from rentals that ended long enough ago.

    The same retention as verification codes: a stored code is a standing risk
    to the account it unlocked. The message rows (when, from whom) stay.
    """
    from apps.rentals.models import RentalMessage

    days = days if days is not None else settings.VERIFYGH["VERIFICATION_DATA_RETENTION_DAYS"]
    cutoff = timezone.now() - timedelta(days=days)
    purged = (RentalMessage.objects
              .filter(rental__ended_at__lt=cutoff)
              .exclude(body="", code="")
              .update(body="", code=""))
    logger.info("rental_messages_purged", extra={"messages": purged, "older_than_days": days})
    return purged


@shared_task(name="apps.rentals.tasks.reconcile_given_up_rentals")
def reconcile_given_up_rentals() -> dict:
    """Follow up purchases refunded for want of an answer (services.reconcile_given_up).

    Recovers what it can from the provider and tells staff about the rest. The
    customer's refund is never revisited.
    """
    due = (Rental.objects.select_related("provider", "service", "user")
           .filter(metadata__reconcile_pending=True).order_by("updated_at")[:BATCH_SIZE])
    checked = 0
    for rental in due:
        try:
            services.reconcile_given_up(rental)
            checked += 1
        except Exception:
            logger.exception("rental_reconcile_failed", extra={"rental": rental.reference})
    if checked:
        logger.info("rentals_reconciled", extra={"checked": checked})
    return {"checked": checked}
