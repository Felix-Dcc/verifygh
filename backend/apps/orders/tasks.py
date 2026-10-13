from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.orders.models import Order, OrderStatus
from apps.orders.services import expire_order, fulfil_order, poll_order

logger = logging.getLogger("verifygh.orders")

#: Cap on how many orders one beat tick will touch upstream. Keeps our provider
#: call rate predictable no matter how busy we get.
POLL_BATCH_SIZE = 50


@shared_task(
    name="apps.orders.tasks.fulfil_order",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def fulfil_order_task(self, order_id: str):
    """Reserve the number with the provider.

    Retries only on unexpected errors. A *handled* provider failure is not
    retried - `fulfil_order` has already failed the order and refunded the
    user, and retrying would buy a number nobody is waiting for.
    """
    order = Order.objects.select_related("provider", "service", "country").filter(
        pk=order_id
    ).first()
    if order is None:
        logger.error("fulfil_order_missing", extra={"order_id": order_id})
        return None

    try:
        order = fulfil_order(order)
    except Exception as exc:
        logger.exception("fulfil_order_unexpected_error", extra={"order": order.reference})
        raise self.retry(exc=exc) from exc

    return order.status


@shared_task(name="apps.orders.tasks.poll_order")
def poll_order_task(order_id: str):
    order = Order.objects.select_related("provider", "service", "country").filter(
        pk=order_id
    ).first()
    if order is None:
        return None
    return poll_order(order).status


@shared_task(name="apps.orders.tasks.poll_active_orders")
def poll_active_orders() -> dict:
    """Poll every order that is genuinely waiting on the provider.

    Only orders that have a provider reservation and have not expired are
    polled - we never spend an upstream call on an order that cannot change.
    """
    now = timezone.now()
    orders = (
        Order.objects.select_related("provider", "service", "country")
        .filter(
            status__in=[
                OrderStatus.PROCESSING,
                OrderStatus.NUMBER_ASSIGNED,
                OrderStatus.WAITING_FOR_CODE,
            ],
            expires_at__gt=now,
        )
        .exclude(provider_order_id="")
        .order_by("created_at")[:POLL_BATCH_SIZE]
    )

    polled = 0
    codes = 0
    for order in orders:
        result = poll_order(order)
        polled += 1
        if result.status == OrderStatus.CODE_RECEIVED:
            codes += 1

    if polled:
        logger.info("orders_polled", extra={"polled": polled, "codes": codes})
    return {"polled": polled, "codes_received": codes}


@shared_task(name="apps.orders.tasks.expire_stale_orders")
def expire_stale_orders() -> dict:
    """Expire orders whose number has run out, and refund them."""
    now = timezone.now()
    stale = Order.objects.select_related("provider", "service", "country", "user").filter(
        status__in=[
            OrderStatus.PROCESSING,
            OrderStatus.NUMBER_ASSIGNED,
            OrderStatus.WAITING_FOR_CODE,
        ],
        expires_at__lt=now,
    )[:100]

    expired = 0
    for order in stale:
        try:
            if order.provider_order_id:
                # One last look: the polling sweep stops at expires_at, so a
                # code that landed in the final seconds would otherwise be
                # refunded - and the provider would still charge us for it.
                order = poll_order(order)
                if order.status == OrderStatus.CODE_RECEIVED:
                    continue
            # Returns at once for an order the last look already settled.
            if expire_order(order).status in (OrderStatus.EXPIRED, OrderStatus.REFUNDED):
                expired += 1
        except Exception:
            logger.exception("order_expiry_failed", extra={"order": order.reference})

    # Orders whose code arrived are closed as COMPLETED once the number's window
    # passes - never refunded, the service was delivered. Without this they stay
    # "active" forever, and after five a customer can no longer buy anything.
    from apps.orders.services import complete_order

    delivered = Order.objects.select_related("provider", "service", "country", "user").filter(
        status=OrderStatus.CODE_RECEIVED, expires_at__lt=now
    )[:100]

    completed = 0
    for order in delivered:
        try:
            complete_order(order)
            completed += 1
        except Exception:
            logger.exception("order_autocomplete_failed", extra={"order": order.reference})

    if expired or completed:
        logger.info("orders_swept", extra={"expired": expired, "auto_completed": completed})
    return {"expired": expired, "auto_completed": completed}


@shared_task(name="apps.orders.tasks.purge_verification_data")
def purge_verification_data(days: int | None = None) -> int:
    """Erase verification codes and SMS text from finished orders.

    A code is only useful for minutes, but a stored one is a liability for
    ever: anyone who reads the database later could use it against the
    account it unlocked. The order, its price and its timeline stay - they are
    financial records - and `code_received_at` stays too, because the refund
    policy relies on it to know that the service was delivered.
    """
    from datetime import timedelta

    from django.conf import settings

    from apps.orders.models import TERMINAL_ORDER_STATUSES

    # Keyed on created_at: orders reach a final state within their TTL
    # (minutes), and bulk .update() calls elsewhere do not bump updated_at.
    days = days if days is not None else settings.VERIFYGH["VERIFICATION_DATA_RETENTION_DAYS"]
    cutoff = timezone.now() - timedelta(days=days)
    purged = (
        Order.objects.filter(status__in=TERMINAL_ORDER_STATUSES, created_at__lt=cutoff)
        .exclude(verification_code="", verification_message="")
        .update(verification_code="", verification_message="")
    )
    logger.info("verification_data_purged", extra={"orders": purged, "older_than_days": days})
    return purged
