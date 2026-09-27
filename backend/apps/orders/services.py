"""Order orchestration.

This is the only module that coordinates wallet, pricing and provider. The shape
of every operation is the same:

    1. check the user is allowed to do this (eligibility, limits, AUP)
    2. re-derive the price on the server; never read it from the request
    3. move money inside a transaction
    4. talk to the provider *outside* that transaction
    5. refund automatically if step 4 gives the user nothing

Step 4 is deliberately outside the money transaction: holding a DB transaction
open across a network call to a third party is how you get lock pile-ups and
timeouts under load.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import SuspicionLevel, SuspiciousActivity
from apps.audit.services import flag, record_audit
from apps.catalog.models import Country, ProviderService, Service
from apps.common.errors import (
    Conflict,
    EmailNotVerified,
    InvalidStateTransition,
    LimitExceeded,
    NotFound,
    ProviderError,
    ServiceUnavailable,
    TermsNotAccepted,
)
from apps.common.ids import order_reference, refund_reference
from apps.common.money import TWO_PLACES, ZERO, quantize, round_to
from apps.orders.models import (
    ACTIVE_ORDER_STATUSES,
    ALLOWED_TRANSITIONS,
    Order,
    OrderEvent,
    OrderStatus,
    Refund,
    RefundReason,
    RefundStatus,
)
from apps.pricing.engine import quote_for_offering
from apps.verification.base import ProviderOrderState
from apps.verification.registry import get_provider
from apps.wallet.models import FundType, LedgerEntryType
from apps.wallet.services import charge_order, credit_refund, get_or_create_wallet

logger = logging.getLogger("verifygh.orders")

STATUS_LABELS = {
    OrderStatus.CREATED: "Order created",
    OrderStatus.PAYMENT_PENDING: "Waiting for payment",
    OrderStatus.PROCESSING: "Payment confirmed",
    OrderStatus.NUMBER_ASSIGNED: "Number assigned",
    OrderStatus.WAITING_FOR_CODE: "Waiting for verification code",
    OrderStatus.CODE_RECEIVED: "Verification code received",
    OrderStatus.COMPLETED: "Completed",
    OrderStatus.EXPIRED: "Expired",
    OrderStatus.CANCELLED: "Cancelled",
    OrderStatus.FAILED: "Failed",
    OrderStatus.REFUNDED: "Refunded",
}


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def transition(order: Order, new_status: str, *, detail: str = "", actor=None,
               metadata: dict | None = None, extra_fields: dict | None = None) -> Order:
    """Move an order to `new_status`, or raise.

    Uses a conditional UPDATE guarded by the current status, so two workers
    racing to advance the same order cannot both win.
    """
    if new_status == order.status:
        return order

    if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        logger.warning(
            "invalid_order_transition",
            extra={"order": order.reference, "from": order.status, "to": new_status},
        )
        raise InvalidStateTransition(
            f"An order that is {order.status} cannot become {new_status}."
        )

    fields = {"status": new_status, **(extra_fields or {})}
    changed = Order.objects.filter(pk=order.pk, status=order.status).update(**fields)
    if changed != 1:
        # Somebody else advanced it first. Re-read and let the caller decide.
        order.refresh_from_db()
        logger.info(
            "order_transition_lost_race",
            extra={"order": order.reference, "now": order.status},
        )
        return order

    OrderEvent.objects.create(
        order=order,
        status=new_status,
        label=STATUS_LABELS.get(new_status, new_status),
        detail=detail[:255],
        is_system=actor is None,
        actor=actor,
        metadata=metadata or {},
    )

    order.refresh_from_db()
    logger.info(
        "order_transitioned",
        extra={"order": order.reference, "status": new_status},
    )
    return order


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def check_purchase_eligibility(user) -> None:
    """Everything that must be true before a user may buy.

    Ordered cheapest-first, and each raises a distinct error code so the
    frontend can show the right call to action rather than a generic failure.
    """
    if user.is_suspended:
        from apps.common.errors import AccountSuspended

        raise AccountSuspended()

    if not user.has_accepted_current_terms:
        raise TermsNotAccepted()

    if settings.VERIFYGH["REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE"] and not user.is_email_verified:
        raise EmailNotVerified()

    active = Order.objects.filter(user=user, status__in=ACTIVE_ORDER_STATUSES).count()
    max_active = settings.VERIFYGH["MAX_ACTIVE_ORDERS"]
    if active >= max_active:
        raise LimitExceeded(
            f"You already have {active} orders in progress. "
            "Finish or cancel one before starting another.",
            code="TOO_MANY_ACTIVE_ORDERS",
        )

    # Platform-wide, across every user: our supplier caps how many numbers one
    # account may hold at once. Checked here, before any money moves, so a full
    # queue is a polite refusal rather than a debited wallet and an upstream
    # rejection. Distinct from the per-user cap above, and phrased so the user
    # knows it is us and not them.
    platform_cap = int(settings.VERIFYGH["MAX_PLATFORM_ACTIVE_ORDERS"])
    if platform_cap:
        in_flight = Order.objects.filter(status__in=ACTIVE_ORDER_STATUSES).count()
        if in_flight >= platform_cap:
            logger.warning(
                "platform_capacity_reached",
                extra={"in_flight": in_flight, "cap": platform_cap},
            )
            raise ServiceUnavailable(
                "We are at capacity right now. Please try again in a few minutes.",
                code="PLATFORM_AT_CAPACITY",
            )

    since = timezone.now() - timedelta(days=1)
    today_orders = Order.objects.filter(user=user, created_at__gte=since).count()
    if today_orders >= settings.VERIFYGH["MAX_ORDERS_PER_DAY"]:
        flag(
            user=user,
            kind=SuspiciousActivity.Kind.VELOCITY_LIMIT,
            level=SuspicionLevel.MEDIUM,
            description=f"Hit the daily order cap ({today_orders} in 24h).",
        )
        raise LimitExceeded(
            "You have reached the daily order limit. Please try again tomorrow.",
            code="DAILY_ORDER_LIMIT",
        )

    spend_cap = quantize(settings.VERIFYGH["MAX_DAILY_SPEND"])
    wallet = get_or_create_wallet(user)
    from django.db.models import Sum

    spent_today = wallet.ledger_entries.filter(
        entry_type=LedgerEntryType.PURCHASE, created_at__gte=since
    ).aggregate(total=Sum("amount"))["total"] or quantize("0")
    if spent_today >= spend_cap:
        raise LimitExceeded(
            f"You have reached the daily spending limit of GHS {spend_cap}.",
            code="DAILY_SPEND_LIMIT",
        )


# ---------------------------------------------------------------------------
# Quoting
# ---------------------------------------------------------------------------


def resolve_offering(service_slug: str, country_code: str) -> ProviderService:
    """Find the best purchasable offering for a (service, country) pair."""
    service = Service.objects.filter(slug=service_slug).first()
    if service is None:
        raise NotFound("We do not offer that service.")
    country = Country.objects.filter(code=country_code.upper()).first()
    if country is None:
        raise NotFound("We do not offer that country.")

    if not service.is_enabled:
        raise ServiceUnavailable("That service is not available right now.",
                                 code="SERVICE_DISABLED")
    if service.is_maintenance:
        raise ServiceUnavailable(
            service.maintenance_note or "That service is temporarily under maintenance.",
            code="SERVICE_MAINTENANCE",
        )
    if not country.is_enabled:
        raise ServiceUnavailable("That country is not available right now.",
                                 code="COUNTRY_DISABLED")

    offering = (
        ProviderService.objects.select_related("provider", "service", "country")
        .filter(
            service=service,
            country=country,
            is_enabled=True,
            is_available=True,
            provider__is_enabled=True,
        )
        .order_by("provider__priority", "cost_amount")
        .first()
    )
    if offering is None:
        raise ServiceUnavailable(
            "No numbers are available for that service and country right now.",
            code="NO_AVAILABILITY",
        )
    return offering


def quote(service_slug: str, country_code: str) -> dict:
    offering = resolve_offering(service_slug, country_code)
    priced = quote_for_offering(offering)
    return {
        "service": offering.service.slug,
        "service_name": offering.service.name,
        "country": offering.country.code,
        "country_name": offering.country.name,
        "price": str(priced.customer_price),
        "currency": priced.currency,
        "supports_sms": offering.supports_sms,
        "supports_voice": offering.supports_voice,
        "ttl_minutes": offering.ttl_minutes,
        "available_count": offering.available_count,
        "offering_id": str(offering.id),
    }


# ---------------------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------------------


def create_order(*, user, service_slug: str, country_code: str, idempotency_key: str,
                 request=None) -> Order:
    """Buy a verification number.

    Money moves in one transaction; the provider is called afterwards by the
    caller (or a Celery task), so a slow provider never holds a wallet lock.
    """
    existing = Order.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing is not None:
        logger.info("order_idempotent_replay", extra={"order": existing.reference})
        return existing

    check_purchase_eligibility(user)

    offering = resolve_offering(service_slug, country_code)
    priced = quote_for_offering(offering)
    price = priced.customer_price

    wallet = get_or_create_wallet(user)
    if wallet.is_frozen:
        from apps.wallet.services import WalletFrozen

        raise WalletFrozen()

    reference = order_reference()

    try:
        with transaction.atomic():
            order = Order.objects.create(
                reference=reference,
                user=user,
                service=offering.service,
                country=offering.country,
                provider=offering.provider,
                provider_service_code=offering.provider_service_code,
                price=price,
                currency=priced.currency,
                provider_cost=priced.provider_cost,
                provider_currency=priced.provider_currency,
                exchange_rate=priced.exchange_rate,
                price_breakdown=priced.as_dict(),
                status=OrderStatus.CREATED,
                idempotency_key=idempotency_key,
                expires_at=timezone.now() + timedelta(minutes=offering.ttl_minutes),
                ip_address=getattr(request, "client_ip", None) or None,
            )

            # Raises InsufficientFunds before anything else is written.
            # Promotional credit is spent first, then cash; see split_charge.
            charge = charge_order(
                wallet=wallet,
                amount=price,
                order_id=order.id,
                order_reference=order.reference,
                service_name=offering.service.name,
            )

            Order.objects.filter(pk=order.pk).update(
                debit_entry_id=getattr(charge.cash_entry, "id", None),
                promo_debit_entry_id=getattr(charge.promo_entry, "id", None),
                promo_amount=charge.promo,
                cash_amount=charge.cash,
                status=OrderStatus.PROCESSING,
            )

            OrderEvent.objects.create(
                order=order,
                status=OrderStatus.CREATED,
                label=STATUS_LABELS[OrderStatus.CREATED],
                detail=f"{offering.service.name} - {offering.country.name}",
            )
            OrderEvent.objects.create(
                order=order,
                status=OrderStatus.PROCESSING,
                label=STATUS_LABELS[OrderStatus.PROCESSING],
                detail=(
                    f"GHS {charge.cash} debited from your wallet and "
                    f"GHS {charge.promo} from your promotional credit."
                    if charge.promo > 0
                    else f"GHS {price} debited from your wallet."
                ),
            )
    except IntegrityError:
        # Lost the race on UNIQUE(user, idempotency_key): the concurrent request
        # already created this order.
        duplicate = Order.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if duplicate is not None:
            return duplicate
        raise

    order.refresh_from_db()
    record_audit(
        actor=user, action="ORDER_CREATED", target=order, request=request,
        metadata={
            "reference": order.reference,
            "service": offering.service.slug,
            "country": offering.country.code,
            "price": str(price),
        },
    )
    logger.info(
        "order_created",
        extra={"order": order.reference, "price": str(price), "service": offering.service.slug},
    )
    return order


def fulfil_order(order: Order) -> Order:
    """Reserve a number with the provider.

    Any failure here refunds the user immediately - they paid for a number and
    did not get one.
    """
    if order.status != OrderStatus.PROCESSING:
        return order

    provider = get_provider(order.provider.adapter_key)

    try:
        result = provider.create_order(
            order.provider_service_code or order.service.slug,
            order.country.code,
            # Deterministic, so a retried task cannot reserve two numbers.
            idempotency_key=f"vgh:{order.id}",
        )
    except (ProviderError, ServiceUnavailable) as exc:
        logger.warning(
            "order_provider_create_failed",
            extra={"order": order.reference, "error": exc.__class__.__name__},
        )
        return fail_order(order, reason="The provider could not supply a number.")

    if result.state == ProviderOrderState.FAILED:
        return fail_order(
            order,
            reason=result.failure_reason or "The provider could not supply a number.",
            provider_order_id=result.provider_order_id,
        )

    if result.state == ProviderOrderState.PENDING or not result.phone_number:
        # The provider accepted the reservation but has not allocated a number
        # yet. Record the id so polling can find it, and leave the order in
        # PROCESSING rather than claiming a number we do not have.
        Order.objects.filter(pk=order.pk).update(
            provider_order_id=result.provider_order_id
        )
        order.refresh_from_db()
        logger.info("order_awaiting_number", extra={"order": order.reference})
        return order

    expires_at = result.expires_at or (
        timezone.now() + timedelta(minutes=settings.VERIFYGH["ORDER_TTL_MINUTES"])
    )

    order = transition(
        order,
        OrderStatus.NUMBER_ASSIGNED,
        detail=result.phone_number or "",
        extra_fields={
            "provider_order_id": result.provider_order_id,
            "phone_number": result.phone_number,
            "expires_at": expires_at,
        },
    )

    from apps.notifications.services import notify

    notify(
        order.user,
        event="NUMBER_ASSIGNED",
        title="Your number is ready",
        body=f"{order.service.name}: {result.phone_number}",
        channels=("IN_APP",),
        metadata={"order_reference": order.reference},
    )

    if order.status == OrderStatus.NUMBER_ASSIGNED:
        order = transition(order, OrderStatus.WAITING_FOR_CODE)
    return order


def poll_order(order: Order) -> Order:
    """Ask the provider whether anything has arrived.

    Called on a schedule with backoff, never in a tight loop - we stay inside
    the provider's published rate limits by design.
    """
    if order.status not in {
        OrderStatus.PROCESSING,
        OrderStatus.NUMBER_ASSIGNED,
        OrderStatus.WAITING_FOR_CODE,
    }:
        return order
    if not order.provider_order_id:
        return order

    provider = get_provider(order.provider.adapter_key)

    try:
        result = provider.get_order_status(order.provider_order_id)
    except (ProviderError, ServiceUnavailable):
        logger.warning("order_poll_failed", extra={"order": order.reference})
        return order

    if result.state == ProviderOrderState.CODE_RECEIVED and result.code:
        return record_code(order, result.code)

    if result.state == ProviderOrderState.EXPIRED:
        return expire_order(order)

    if result.state in {ProviderOrderState.FAILED, ProviderOrderState.CANCELLED}:
        return fail_order(order, reason=result.failure_reason or "The provider ended this order.")

    if result.phone_number and order.status == OrderStatus.PROCESSING:
        # The number has now been allocated - catch the order up.
        order = transition(
            order,
            OrderStatus.NUMBER_ASSIGNED,
            detail=result.phone_number,
            extra_fields={
                "phone_number": result.phone_number,
                "expires_at": result.expires_at or order.expires_at,
            },
        )
        if order.status == OrderStatus.NUMBER_ASSIGNED:
            order = transition(order, OrderStatus.WAITING_FOR_CODE)
    elif result.phone_number and not order.phone_number:
        Order.objects.filter(pk=order.pk).update(phone_number=result.phone_number)
        order.refresh_from_db()

    return order


def record_code(order: Order, code_dto) -> Order:
    """Store a received code.

    Whether the *user* may see it is decided at serialisation time by
    `Order.may_display_code`; we still store it so support can resolve disputes.
    """
    order = transition(
        order,
        OrderStatus.CODE_RECEIVED,
        detail="A verification code was received.",
        extra_fields={
            "verification_code": (code_dto.code or "")[:32],
            "verification_message": (code_dto.full_text or "")[:2000],
            "code_received_at": code_dto.received_at or timezone.now(),
        },
    )

    from apps.notifications.services import notify

    notify(
        order.user,
        event="CODE_RECEIVED",
        title="Verification code received",
        body=f"Your {order.service.name} verification code has arrived.",
        channels=("IN_APP",),
        metadata={"order_reference": order.reference},
    )
    # The code itself is never written to a log or a notification body.
    logger.info("order_code_received", extra={"order": order.reference})
    return order


def complete_order(order: Order, *, actor=None) -> Order:
    if order.status != OrderStatus.CODE_RECEIVED:
        raise InvalidStateTransition(
            "You can only complete an order once a verification code has arrived."
        )
    order = transition(
        order,
        OrderStatus.COMPLETED,
        detail="Marked complete.",
        actor=actor,
        extra_fields={"completed_at": timezone.now()},
    )
    from apps.notifications.services import notify

    notify(
        order.user,
        event="ORDER_COMPLETED",
        title="Order completed",
        body=f"Your {order.service.name} verification is complete.",
        channels=("EMAIL", "IN_APP"),
        metadata={"order_reference": order.reference},
    )
    return order


def cancel_order(order: Order, *, actor=None, reason: str = "") -> Order:
    """Cancel and refund, where the provider permits it."""
    if order.status in {OrderStatus.CODE_RECEIVED, OrderStatus.COMPLETED}:
        raise Conflict(
            "This order cannot be cancelled because the verification code has already arrived.",
            code="CANCEL_NOT_ALLOWED",
        )
    if order.is_terminal:
        raise InvalidStateTransition("This order is already closed.")

    provider_accepted = True
    if order.provider_order_id:
        provider = get_provider(order.provider.adapter_key)
        try:
            provider_accepted = provider.cancel_order(order.provider_order_id)
        except (ProviderError, ServiceUnavailable):
            provider_accepted = False
            logger.warning("order_provider_cancel_failed", extra={"order": order.reference})

    if not provider_accepted:
        raise Conflict(
            "The provider could not cancel this order. It will expire on its own if no "
            "code arrives.",
            code="PROVIDER_CANCEL_REFUSED",
        )

    order = transition(
        order,
        OrderStatus.CANCELLED,
        detail=reason or "Cancelled at your request.",
        actor=actor,
        extra_fields={"completed_at": timezone.now()},
    )
    return issue_refund(order, reason=RefundReason.USER_CANCELLED, actor=actor, automatic=True)


def expire_order(order: Order) -> Order:
    if order.is_terminal:
        return order
    order = transition(
        order,
        OrderStatus.EXPIRED,
        detail="No verification code arrived before the number expired.",
        extra_fields={"completed_at": timezone.now()},
    )

    from apps.notifications.services import notify

    notify(
        order.user,
        event="ORDER_EXPIRED",
        title="Order expired",
        body=f"No code arrived for your {order.service.name} order. A refund is on its way.",
        channels=("IN_APP",),
        metadata={"order_reference": order.reference},
    )
    return issue_refund(order, reason=RefundReason.NO_CODE_RECEIVED, automatic=True)


def fail_order(order: Order, *, reason: str, provider_order_id: str = "") -> Order:
    extra = {"failure_reason": reason[:255], "completed_at": timezone.now()}
    if provider_order_id:
        extra["provider_order_id"] = provider_order_id

    order = transition(order, OrderStatus.FAILED, detail=reason, extra_fields=extra)
    return issue_refund(order, reason=RefundReason.PROVIDER_FAILED, automatic=True)


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


def split_refund(order: Order, amount) -> tuple[Decimal, Decimal]:
    """Split a refund back into (promotional, cash), matching how it was paid.

    A refund must not turn promotional credit into withdrawable cash. For a
    full refund each bucket simply gets back what it paid. For a partial one
    the split is proportional, with the rounding remainder given to the
    promotional side, so the cash returned is never more than its true share.
    """
    amount = quantize(amount)
    promo_paid = quantize(order.promo_amount)
    cash_paid = quantize(order.cash_amount)
    price = quantize(promo_paid + cash_paid)

    if price <= ZERO:
        # Orders placed before promotional credit existed recorded no split.
        return ZERO, amount
    if amount >= price:
        return promo_paid, cash_paid

    promo_part = min(promo_paid, round_to(amount * promo_paid / price, TWO_PLACES, ceiling=True))
    return promo_part, quantize(amount - promo_part)


def issue_refund(order: Order, *, reason: str, amount=None, actor=None, note: str = "",
                 automatic: bool = True) -> Order:
    """Refund an order.

    Refund policy, in one place:
      * provider never supplied a number      -> full refund
      * number supplied, no code, expired     -> full refund
      * cancelled before a code arrived       -> full refund
      * code delivered (service rendered)     -> no automatic refund
      * anything else                         -> an admin decides, with a reason

    Every refund creates an immutable ledger entry. The OneToOne on Refund means
    a second attempt cannot create a second credit.
    """
    if order.refund_status == RefundStatus.COMPLETED:
        return order

    code_delivered = bool(order.verification_code or order.code_received_at)
    if order.status == OrderStatus.COMPLETED or (automatic and code_delivered):
        # The user received what they paid for. Checked on the code itself, not
        # only the status, so no future transition path can turn a delivered
        # service into an automatic refund. Admin refunds (automatic=False)
        # remain possible, with a recorded reason.
        logger.info("refund_declined_service_rendered", extra={"order": order.reference})
        return order

    refund_amount = quantize(amount if amount is not None else order.price)
    if refund_amount <= 0:
        return order

    wallet = get_or_create_wallet(order.user)

    try:
        with transaction.atomic():
            refund, created = Refund.objects.get_or_create(
                order=order,
                defaults={
                    "reference": refund_reference(),
                    "amount": refund_amount,
                    "currency": order.currency,
                    "reason": reason,
                    "note": note[:255],
                    "is_automatic": automatic,
                    "issued_by": actor,
                    "status": RefundStatus.PENDING,
                },
            )
            if not created and refund.status == RefundStatus.COMPLETED:
                return order

            promo_part, cash_part = split_refund(order, refund_amount)
            promo_entry = None
            if promo_part > 0:
                promo_entry = credit_refund(
                    wallet=wallet,
                    amount=promo_part,
                    idempotency_key=f"refund:{order.id}:promo",
                    order_id=order.id,
                    order_reference=order.reference,
                    reason=reason,
                    funds=FundType.PROMO,
                )
            entry = promo_entry
            if cash_part > 0:
                entry = credit_refund(
                    wallet=wallet,
                    amount=cash_part,
                    idempotency_key=f"refund:{order.id}",
                    order_id=order.id,
                    order_reference=order.reference,
                    reason=reason,
                    funds=FundType.CASH,
                )

            Refund.objects.filter(pk=refund.pk).update(
                status=RefundStatus.COMPLETED,
                ledger_entry_id=entry.id,
                promo_amount=promo_part,
                cash_amount=cash_part,
                completed_at=timezone.now(),
            )

            # The order's final status becomes REFUNDED, but the reason it got
            # there stays readable in failure_reason and in the event timeline.
            order_updates = {"refund_status": RefundStatus.COMPLETED}
            if OrderStatus.REFUNDED in ALLOWED_TRANSITIONS.get(order.status, set()):
                order_updates["status"] = OrderStatus.REFUNDED
            Order.objects.filter(pk=order.pk).update(**order_updates)

            OrderEvent.objects.create(
                order=order,
                status=OrderStatus.REFUNDED,
                label="Refunded",
                detail=f"GHS {refund_amount} returned to your wallet.",
                is_system=actor is None,
                actor=actor,
                metadata={"reason": reason},
            )
    except IntegrityError:
        logger.info("refund_already_exists", extra={"order": order.reference})
        order.refresh_from_db()
        return order

    # Ask the provider for its own refund where its policy allows it. This is
    # our cost recovery and is independent of the user already being made whole.
    _request_provider_refund(order)

    order.refresh_from_db()

    from apps.notifications.services import notify

    notify(
        order.user,
        event="REFUND_ISSUED",
        title="Refund issued",
        body=f"GHS {refund_amount} has been returned to your VerifyGH wallet.",
        channels=("EMAIL", "IN_APP"),
        context={"amount": str(refund_amount), "reference": order.reference},
        metadata={"order_reference": order.reference},
    )
    record_audit(
        actor=actor, action="ORDER_REFUNDED", target=order,
        metadata={"amount": str(refund_amount), "reason": reason, "automatic": automatic},
    )
    logger.info(
        "order_refunded",
        extra={"order": order.reference, "amount": str(refund_amount), "reason": reason},
    )
    return order


def _request_provider_refund(order: Order) -> None:
    if not order.provider_order_id:
        return
    provider = get_provider(order.provider.adapter_key)
    try:
        accepted = provider.refund_order(order.provider_order_id)
    except (ProviderError, ServiceUnavailable):
        logger.warning("provider_refund_request_failed", extra={"order": order.reference})
        return
    Refund.objects.filter(order=order).update(
        provider_refund_requested=True, provider_refund_accepted=bool(accepted)
    )
