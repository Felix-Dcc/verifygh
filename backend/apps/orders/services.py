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
from apps.common.money import TWO_PLACES, ZERO, format_ghs, quantize, round_to
from apps.orders.models import (
    ACTIVE_ORDER_STATUSES,
    ALLOWED_TRANSITIONS,
    UPSTREAM_ORDER_STATUSES,
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
from apps.wallet.models import FundType
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
    from apps.common import maintenance

    # First: while staff have paused the site, nothing else matters.
    maintenance.require_buying_open()

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
        in_flight = Order.objects.filter(status__in=UPSTREAM_ORDER_STATUSES).count()
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
    from apps.wallet.services import net_spending

    # Refunded orders do not count towards the limit: the money came back.
    spent_today = net_spending(wallet, created_at__gte=since)
    if spent_today >= spend_cap:
        raise LimitExceeded(
            f"You have reached the daily spending limit of {format_ghs(spend_cap)}.",
            code="DAILY_SPEND_LIMIT",
        )


# ---------------------------------------------------------------------------
# Quoting
# ---------------------------------------------------------------------------


def resolve_offering(service_slug: str, country_code: str) -> ProviderService:
    """The preferred offering for a (service, country) pair - what we quote."""
    return candidate_offerings(service_slug, country_code)[0]


def candidate_offerings(service_slug: str, country_code: str) -> list[ProviderService]:
    """Every offering that could fill a (service, country) order, best first.

    Only providers that are enabled, have a registered adapter *and* have
    authorised us in writing to resell their numbers qualify - a provider we
    are not authorised to resell never gets here. The country is
    checked against the marketplace list before anything else: a request for a
    country we do not sell is refused even if the catalogue happens to hold an
    offering for it.
    """
    from apps.catalog.marketplace import require_marketplace_country
    from apps.verification.registry import available_adapters

    country_code = require_marketplace_country(country_code)
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

    offerings = list(
        ProviderService.objects.select_related("provider", "service", "country")
        .filter(
            service=service,
            country=country,
            is_enabled=True,
            is_available=True,
            provider__is_enabled=True,
            provider__resale_authorized=True,
            provider__adapter_key__in=available_adapters(),
        )
        .order_by("provider__priority", "cost_amount")
    )
    if not offerings:
        raise ServiceUnavailable(
            "No numbers are available for that service and country right now.",
            code="NO_AVAILABILITY",
        )
    return offerings


def purchasable_offering(service_slug: str, country_code: str) -> ProviderService:
    """The offering to buy from, checked just before any money moves.

    Each candidate must pass two checks: our prepaid balance at its provider
    can pay for the number (apps/funding), and the provider has one in stock
    right now. The first that passes wins; the rest are failover. A fallback
    is only taken at or below the price of the preferred offering, because
    that is the price the customer was shown.

    When balances are what stopped us, the customer hears "temporarily
    unavailable" and staff get the real reason.
    """
    from apps.funding import services as funding

    candidates = candidate_offerings(service_slug, country_code)
    blocked: list[tuple[ProviderService, funding.FundingCheck]] = []
    last_error: ServiceUnavailable | None = None
    ceiling = None

    for index, offering in enumerate(candidates):
        if index:
            try:
                if ceiling is None:
                    ceiling = quote_for_offering(candidates[0]).customer_price
                if quote_for_offering(offering).customer_price > ceiling:
                    continue
            except (ServiceUnavailable, ProviderError, ValueError):
                continue
            except Exception:
                logger.exception("failover_quote_failed", extra={"offering": str(offering.pk)})
                continue

        check = funding.check_funding(offering)
        if not check.ok:
            blocked.append((offering, check))
            continue
        try:
            confirm_live_availability(offering)
        except ServiceUnavailable as exc:
            last_error = exc
            continue
        if index:
            logger.warning("order_failover", extra={
                "from": candidates[0].provider.adapter_key,
                "to": offering.provider.adapter_key, "service": offering.service.slug,
            })
        return offering

    for offering, check in blocked:
        funding.purchase_blocked(offering, check)
    if blocked:
        raise ServiceUnavailable(funding.CUSTOMER_UNAVAILABLE, code="TEMPORARILY_UNAVAILABLE")
    raise last_error or ServiceUnavailable(
        "No numbers are available for that service and country right now.",
        code="NO_AVAILABILITY",
    )


def confirm_live_availability(offering: ProviderService) -> None:
    """Ask the provider, not the last sync, whether a number can be had now.

    Called before any money moves. A refusal here costs the customer nothing;
    the same refusal after charging would cost them a refund round trip. The
    answer also refreshes the catalogue row, so the marketplace catches up.
    """
    from apps.catalog import stock

    # Always fresh: a cached answer is for the listing, never for a purchase.
    live = stock.check(offering, max_age=0)
    if live.state == stock.ERROR:
        logger.warning("live_availability_check_failed", extra={"offering": str(offering.pk)})
        raise ServiceUnavailable(
            "Our number provider is not responding right now. Nothing was charged - "
            "please try again in a moment.",
            code="PROVIDER_UNAVAILABLE",
        )
    if not live.in_stock:
        raise ServiceUnavailable(
            "No numbers are available for that service and country right now. "
            "Nothing was charged.",
            code="NO_AVAILABILITY",
        )


def quote(service_slug: str, country_code: str) -> dict:
    from apps.catalog.marketplace import availability

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
        **availability(offering),
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

    # Everything the price depends on is re-derived here, never taken from the
    # request: which offering, whether our provider balance covers it, whether
    # it is in stock right now, and what it costs. The client sends a service
    # slug and a country code, nothing else.
    offering = purchasable_offering(service_slug, country_code)
    priced = quote_for_offering(offering)
    return _place_order(user=user, offering=offering, priced=priced,
                        idempotency_key=idempotency_key, request=request)


def _place_order(*, user, offering, priced, idempotency_key: str, request=None,
                 metadata: dict | None = None, created_detail: str = "") -> Order:
    """Charge the wallet and create the order, in one transaction.

    Shared by a new purchase and a number reuse, so both move money the same
    way: ledger-first, idempotent on (user, key), and never holding a wallet
    lock across a provider call.
    """
    price = priced.customer_price

    wallet = get_or_create_wallet(user)
    if wallet.is_frozen:
        from apps.wallet.services import WalletFrozen

        raise WalletFrozen()

    # The eligibility check refuses once the limit is reached; this one also
    # counts the purchase being made, so a single order cannot carry the day's
    # spending past it.
    from apps.wallet.services import net_spending

    spend_cap = quantize(settings.VERIFYGH["MAX_DAILY_SPEND"])
    spent_today = net_spending(wallet, created_at__gte=timezone.now() - timedelta(days=1))
    if spent_today + quantize(price) > spend_cap:
        raise LimitExceeded(
            f"This would take you past the daily spending limit of {format_ghs(spend_cap)}.",
            code="DAILY_SPEND_LIMIT",
        )

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
                metadata=metadata or {},
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
                detail=created_detail or f"{offering.service.name} - {offering.country.name}",
            )
            OrderEvent.objects.create(
                order=order,
                status=OrderStatus.PROCESSING,
                label=STATUS_LABELS[OrderStatus.PROCESSING],
                detail=(
                    f"{format_ghs(charge.cash)} debited from your wallet and "
                    f"{format_ghs(charge.promo)} from your promotional credit."
                    if charge.promo > 0
                    else f"{format_ghs(price)} debited from your wallet."
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


# ---------------------------------------------------------------------------
# Reusing a number
# ---------------------------------------------------------------------------


REUSABLE_STATUSES = {OrderStatus.CODE_RECEIVED, OrderStatus.COMPLETED}


def reuse_blocker(order: Order) -> str:
    """Why this order's number cannot be used again right now, or "" if it can.

    Reuse is offered only where the provider documents it and says, per
    verification, until when (TextVerified: `reuse.reusableUntil`, a couple
    of minutes after the code arrives).
    """
    from apps.verification.registry import available_adapters, get_provider

    if order.status not in REUSABLE_STATUSES:
        return "Only a number that has received its code can be used again."
    if not order.provider_order_id or not order.phone_number:
        return "This number cannot be used again."
    if not order.reusable_until or order.reusable_until <= timezone.now():
        return "The window to use this number again has closed."
    provider = order.provider
    if not (provider.is_enabled and provider.resale_authorized
            and provider.adapter_key in available_adapters()):
        return "This number cannot be used again right now."
    if not get_provider(provider.adapter_key).supports_reuse:
        return "This number cannot be used again."
    return ""


#: How long the order page trusts the provider's "can reactivate" answer.
REACTIVATION_CHECK_SECONDS = 300


#: Reactivation metadata: the price of the first order in the chain.
REACTIVATION_BASE_KEY = "reactivation_base_price"


def reactivation_base(order: Order) -> Decimal:
    """What the number first sold for, however many times it was reactivated since.

    A reactivation is itself reactivatable, and halving *its* price halved
    again - 13 Oct: GH₵6.75, then GH₵3.38, below what the provider charges.
    The base is carried forward on each reactivation; older ones (before it
    was) are followed back through `reuse_of` to the first order.
    """
    current = order
    for _ in range(20):
        meta = current.metadata or {}
        if meta.get(REACTIVATION_BASE_KEY):
            return Decimal(str(meta[REACTIVATION_BASE_KEY]))
        if "reactivate_of_provider_order_id" not in meta:
            break
        parent = Order.objects.filter(user_id=current.user_id,
                                      reference=meta.get("reuse_of", "")).first()
        if parent is None:
            break
        current = parent
    return Decimal(current.price)


def reactivation_price(order: Order) -> Decimal:
    """Half of what the customer paid for the number's first order, rounded up
    to the pesewa - as TextVerified prices its own reactivation (0.38 after 0.75)."""
    from decimal import ROUND_CEILING

    return (reactivation_base(order) / 2).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def reactivation_blocker(order: Order, *, live: bool = False) -> str:
    """Why this order's number cannot be reactivated now, or "" if it can.

    Reactivation is for after the reuse window: while reuse is open, that is
    the offer. The provider decides eligibility per verification
    (TextVerified: `reactivate.canReactivate`); the order page reads a cached
    answer, a purchase always asks again (`live`).
    """
    from django.core.cache import cache

    from apps.verification.registry import available_adapters, get_provider

    if order.status not in REUSABLE_STATUSES:
        return "Only a number that has received its code can be reactivated."
    if not order.provider_order_id or not order.phone_number:
        return "This number cannot be reactivated."
    if order.reusable_until and order.reusable_until > timezone.now():
        return "This number can still be used again directly."
    provider = order.provider
    if not (provider.is_enabled and provider.resale_authorized
            and provider.adapter_key in available_adapters()):
        return "This number cannot be reactivated right now."
    client = get_provider(provider.adapter_key)
    if not client.supports_reactivation:
        return "This number cannot be reactivated."

    key = f"order-reactivation:{order.pk}"
    eligible = None if live else cache.get(key)
    if eligible is None:
        try:
            eligible = client.can_reactivate(order.provider_order_id)
        except (ProviderError, ServiceUnavailable):
            return "We could not check this number right now. Please try again shortly."
        cache.set(key, eligible, REACTIVATION_CHECK_SECONDS)
    return "" if eligible else "Our number provider can no longer reactivate this number."


def _another_code_on_the_number(*, user, original: Order, idempotency_key: str, request,
                                blocker: str, code: str, metadata: dict, label: str,
                                price: Decimal | None = None) -> Order:
    """Shared by reuse and reactivation: a new order, charged like a purchase."""
    from apps.funding import services as funding

    if blocker:
        raise Conflict(blocker, code=code)

    check_purchase_eligibility(user)

    offering = next(
        (candidate for candidate in candidate_offerings(original.service.slug,
                                                        original.country.code)
         if candidate.provider_id == original.provider_id),
        None,
    )
    if offering is None:
        raise ServiceUnavailable(
            "This number cannot be used again right now. Nothing was charged.", code=code)
    check = funding.check_funding(offering)
    if not check.ok:
        funding.purchase_blocked(offering, check)
        raise ServiceUnavailable(funding.CUSTOMER_UNAVAILABLE, code="TEMPORARILY_UNAVAILABLE")

    priced = quote_for_offering(offering)
    if price is not None:
        # A set price is applied after the engine's own below-cost check, so it
        # needs one of its own. The provider charges for a reactivation about
        # half a new number (0.38 after 0.75); never ask less than that.
        floor = quantize(Decimal(priced.base_cost) / 2)
        if price < floor:
            logger.error("set_price_below_cost_refused",
                         extra={"original": original.reference, "price": str(price),
                                "floor": str(floor)})
            raise ServiceUnavailable(
                "This number cannot be used again right now. Nothing was charged.", code=code)
        # A set price (reactivation): the quote keeps its costs for the record,
        # and says why the customer price differs from the service's.
        import dataclasses

        priced = dataclasses.replace(
            priced, customer_price=price,
            applied={**(priced.applied or {}),
                     "set_price": {"price": str(price), "reason": label,
                                   "service_price": str(priced.customer_price)}})
    return _place_order(
        user=user, offering=offering, priced=priced, idempotency_key=idempotency_key,
        request=request, metadata=metadata,
        created_detail=f"{offering.service.name} - {label} ({original.reference})",
    )


def reactivate_number(*, user, original: Order, idempotency_key: str, request=None) -> Order:
    """Another code on the same number after the reuse window, where the provider allows.

    TextVerified's "Reactivate". Charged like a purchase and refunded
    automatically if the provider then refuses. Priced at half
    what the original order cost, as TextVerified prices its own reactivation;
    the order records what it actually cost us.
    """
    existing = Order.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if original.user_id != user.id:
        raise NotFound("We could not find that order.")
    return _another_code_on_the_number(
        user=user, original=original, idempotency_key=idempotency_key, request=request,
        # Asked live: a cached "yes" must not take money for a refusal.
        blocker=reactivation_blocker(original, live=True), code="REACTIVATION_NOT_AVAILABLE",
        metadata={"reuse_of": original.reference,
                  "reactivate_of_provider_order_id": original.provider_order_id,
                  REACTIVATION_BASE_KEY: str(reactivation_base(original))},
        label="same number reactivated",
        price=reactivation_price(original),
    )


def reuse_number(*, user, original: Order, idempotency_key: str, request=None) -> Order:
    """Buy another code on the same number, while the provider allows it.

    A new order, charged and refunded exactly like a purchase: the same
    eligibility, the same authorisation and funding checks before any money
    moves, and an automatic refund if the provider then refuses. Priced at the
    service's normal price - the provider does not publish a reuse price in
    advance - and the order records what the reuse actually cost us.
    """
    existing = Order.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if original.user_id != user.id:
        raise NotFound("We could not find that order.")
    return _another_code_on_the_number(
        user=user, original=original, idempotency_key=idempotency_key, request=request,
        blocker=reuse_blocker(original), code="REUSE_NOT_AVAILABLE",
        metadata={"reuse_of": original.reference,
                  "reuse_of_provider_order_id": original.provider_order_id},
        label="same number again",
    )


def _actual_cost(result) -> dict:
    """The provider's own figure for what this number cost us, when it gives one.

    The order is priced from the catalogue's cost, but a reuse or reactivation
    costs something else (TextVerified: `totalCost` on the new verification),
    and profit figures are only right if the order keeps what was really paid.
    The quote, catalogue cost included, stays in `price_breakdown`.
    """
    cost = getattr(result, "cost", None)
    try:
        return {"provider_cost": Decimal(cost)} if cost is not None and Decimal(cost) > 0 else {}
    except (ArithmeticError, TypeError, ValueError):
        return {}


def fulfil_order(order: Order) -> Order:
    """Reserve a number with the provider.

    Any failure here refunds the user immediately - they paid for a number and
    did not get one.
    """
    if order.status != OrderStatus.PROCESSING:
        return order

    reuse_of = (order.metadata or {}).get("reuse_of_provider_order_id", "")
    reactivate_of = (order.metadata or {}).get("reactivate_of_provider_order_id", "")

    if not (order.provider.is_enabled and order.provider.resale_authorized):
        # Checked again here, not only when the order was priced: a provider can
        # be switched off, or its authorisation withdrawn, between the charge
        # and this task. No number is requested; the customer is refunded.
        logger.warning("order_provider_not_authorized",
                       extra={"order": order.reference, "provider": order.provider.adapter_key})
        return fail_order(order, reason="This service is temporarily unavailable.")

    try:
        # Inside the try: an order whose provider has since been removed from
        # the registry must be refunded like any other provider failure, not
        # left in PROCESSING by an exception.
        provider = get_provider(order.provider.adapter_key)
        if reuse_of:
            # The same number again, through the provider's documented reuse.
            result = provider.reuse_order(reuse_of, idempotency_key=f"vgh:{order.id}")
        elif reactivate_of:
            # The same number again after the reuse window: reactivation.
            result = provider.reactivate_order(reactivate_of, idempotency_key=f"vgh:{order.id}")
        else:
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
        try:
            from apps.funding.services import note_provider_failure

            note_provider_failure(order.provider, exc)
        except Exception:
            # Alerting must never stand between the customer and their refund.
            logger.exception("provider_failure_alert_failed")
        provider_code = str(getattr(exc, "provider_code", "") or "")
        staff_detail = (f"{order.provider.name} answered {provider_code}." if provider_code
                        else f"The call to {order.provider.name} failed "
                             f"({exc.__class__.__name__}).")
        if provider_code.lower() == "unavailable":
            # Refused for stock although the inventory check said yes. Believe
            # the refusal, so the next customer is turned away before paying.
            try:
                from apps.catalog import stock

                offering = ProviderService.objects.select_related(
                    "provider", "service", "country").filter(
                    provider=order.provider, service=order.service, country=order.country,
                ).first()
                if offering is not None:
                    stock.note_refused(offering)
            except Exception:
                logger.exception("stock_refusal_note_failed")
            return fail_order(order, reason=(
                f"No {order.service.name} number was available just then. Your money is back "
                "in your wallet - try again in a few minutes."
            ), staff_detail=staff_detail)
        if provider_code.lower() == "toomanyunfinishedverifications":
            # The provider's limit on numbers held at once, across all our
            # customers - not this customer's doing, so not worded as if it were.
            return fail_order(order, reason=(
                "We were handling a lot of orders just then. Your money is back in your "
                "wallet - please try again in a minute."
            ), staff_detail=staff_detail)
        return fail_order(order, reason="The provider could not supply a number.",
                          staff_detail=staff_detail)

    if result.state == ProviderOrderState.FAILED:
        return fail_order(
            order,
            reason=result.failure_reason or "The provider could not supply a number.",
            provider_order_id=result.provider_order_id,
        )

    # Screen out numbers customers have reported for this service. Neither
    # provider lets us ask for "a number never used for TikTok" - OnlineSim's
    # only exclusion is digit masks of an undocumented format - so the check is
    # ours: turn the flagged number away, release it, and draw again.
    from apps.numbers import services as numbers

    redraws = 0
    # A reuse is the customer asking for this very number again: never screened out.
    while (not (reuse_of or reactivate_of) and result.phone_number
           and numbers.is_excluded(order, result.phone_number)):
        numbers.turn_away(order, provider, result)
        if redraws >= int(settings.VERIFYGH["NUMBER_QUALITY_MAX_REDRAWS"]):
            return fail_order(
                order,
                reason="We could not find a suitable number for this service right now.",
            )
        redraws += 1
        try:
            result = provider.create_order(
                order.provider_service_code or order.service.slug,
                order.country.code,
                idempotency_key=f"vgh:{order.id}:redraw:{redraws}",
            )
        except (ProviderError, ServiceUnavailable):
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
            provider_order_id=result.provider_order_id, **_actual_cost(result)
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
            **_actual_cost(result),
        },
    )
    _warn_if_sold_below_cost(order)

    numbers.note_assigned(order)

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


def _warn_if_sold_below_cost(order: Order) -> None:
    """Tell staff when the provider charged more than the customer paid."""
    try:
        cost_ghs = quantize(Decimal(order.provider_cost) * Decimal(order.exchange_rate))
    except (ArithmeticError, TypeError, ValueError):
        return
    if cost_ghs > quantize(order.price):
        logger.error("order_sold_below_cost",
                     extra={"order": order.reference, "price": str(order.price),
                            "cost_ghs": str(cost_ghs)})


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

    try:
        provider = get_provider(order.provider.adapter_key)
        result = provider.get_order_status(order.provider_order_id)
    except (ProviderError, ServiceUnavailable):
        logger.warning("order_poll_failed", extra={"order": order.reference})
        return order

    if result.state == ProviderOrderState.CODE_RECEIVED and result.code:
        return record_code(order, result.code, reusable_until=result.reusable_until)

    if result.state == ProviderOrderState.EXPIRED:
        return expire_order(order)

    if result.state in {ProviderOrderState.FAILED, ProviderOrderState.CANCELLED}:
        return fail_order(order, reason=result.failure_reason or "The provider ended this order.")

    if result.phone_number and order.status == OrderStatus.PROCESSING:
        from apps.numbers import services as numbers

        if numbers.is_excluded(order, result.phone_number):
            # Allocated late, so there is no clean way to draw again from here.
            # Release it and refund rather than sell a flagged number.
            numbers.turn_away(order, provider, result)
            return fail_order(
                order, reason="We could not find a suitable number for this service right now."
            )
        # The number has now been allocated - catch the order up.
        order = transition(
            order,
            OrderStatus.NUMBER_ASSIGNED,
            detail=result.phone_number,
            extra_fields={
                "phone_number": result.phone_number,
                "expires_at": result.expires_at or order.expires_at,
                **_actual_cost(result),
            },
        )
        _warn_if_sold_below_cost(order)
        numbers.note_assigned(order)
        if order.status == OrderStatus.NUMBER_ASSIGNED:
            order = transition(order, OrderStatus.WAITING_FOR_CODE)
    elif result.phone_number and not order.phone_number:
        Order.objects.filter(pk=order.pk).update(phone_number=result.phone_number)
        order.refresh_from_db()

    return order


def record_code(order: Order, code_dto, *, reusable_until=None) -> Order:
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
            "reusable_until": reusable_until,
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

    def _referral():
        # A friend's first completed, partly cash-paid number earns whoever
        # invited them their reward. Never allowed to touch the order itself.
        try:
            from apps.referrals.services import process_referrer_reward_for_user

            process_referrer_reward_for_user(order.user)
        except Exception:
            logger.exception("referrer_reward_after_order_failed",
                             extra={"order": order.reference})

    transaction.on_commit(_referral)
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
    if order.status != OrderStatus.EXPIRED:
        # Lost the race - usually to the code arriving at the last moment. No
        # "no code arrived" message, and no refund for a delivered code.
        return order

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


#: At most one "order did not go through" email per this many seconds; every
#: failure still reaches the admin bell. A provider outage is one email.
ORDER_FAILED_EMAIL_COOLDOWN = 10 * 60


def fail_order(order: Order, *, reason: str, provider_order_id: str = "",
               staff_detail: str = "") -> Order:
    extra = {"failure_reason": reason[:255], "completed_at": timezone.now()}
    if provider_order_id:
        extra["provider_order_id"] = provider_order_id

    order = transition(order, OrderStatus.FAILED, detail=reason, extra_fields=extra)
    if order.status != OrderStatus.FAILED:
        # Lost the race to another outcome (a code, an expiry): that path
        # settles the order, not this one.
        return order
    order = issue_refund(order, reason=RefundReason.PROVIDER_FAILED, automatic=True)
    _alert_staff_order_failed(order, staff_detail or reason)
    return order


def _alert_staff_order_failed(order: Order, detail: str) -> None:
    """Tell the people who can refund that a customer's order did not go through."""
    from apps.accounts.constants import AdminPermission
    from apps.accounts.services import mask_email
    from apps.notifications.staff import alert_staff

    try:
        refunded = (f"refunded {format_ghs(order.price)} automatically"
                    if order.refund_status == RefundStatus.COMPLETED else "not refunded yet")
        alert_staff(
            permission=AdminPermission.ORDER_REFUND,
            event="STAFF_ORDER_FAILED",
            title=f"Order {order.reference} didn't go through",
            body=(f"{order.service.name} ({order.country.code}) for "
                  f"{mask_email(order.user.email)}. {detail} The customer was {refunded}. "
                  "If several fail together, the rest are in Admin > Orders."),
            link=f"/admin/orders?q={order.reference}",
            reference=order.reference,
            cooldown_key="staff-alert:order-failed:email",
            cooldown_seconds=ORDER_FAILED_EMAIL_COOLDOWN,
        )
    except Exception:
        # Telling staff must never stand between the customer and their refund.
        logger.exception("staff_order_failed_alert_failed", extra={"order": order.reference})


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
                 automatic: bool = True, override_delivered: bool = False,
                 provider_refunded: bool = False) -> Order:
    """Refund an order.

    Refund policy, in one place:
      * provider never supplied a number      -> full refund
      * number supplied, no code, expired     -> full refund
      * cancelled before a code arrived       -> full refund
      * code delivered (service rendered)     -> no automatic refund
      * anything else                         -> an admin decides, with a reason

    `override_delivered` is the one exception to "a delivered code is a
    delivered service": staff upholding a customer's report that the number
    could not be used (apps/numbers). It is never automatic - the caller must
    also pass automatic=False and an actor - and it is audited like any refund.

    `provider_refunded` is the one way it may happen without a person: the
    provider reviewed the customer's report and refunded us for that very
    verification, which is the decision a person would otherwise make. We
    then do not ask the provider for a refund it has already given.

    Every refund creates an immutable ledger entry. The OneToOne on Refund means
    a second attempt cannot create a second credit.
    """
    if order.refund_status == RefundStatus.COMPLETED:
        return order

    if override_delivered and not provider_refunded and (automatic or actor is None):
        raise ValueError("override_delivered needs a staff actor and automatic=False.")

    code_delivered = bool(order.verification_code or order.code_received_at)
    if not override_delivered and (
        order.status == OrderStatus.COMPLETED or (automatic and code_delivered)
    ):
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
                detail=f"{format_ghs(refund_amount)} returned to your wallet.",
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
    if provider_refunded:
        Refund.objects.filter(order=order).update(
            provider_refund_requested=True, provider_refund_accepted=True
        )
    else:
        _request_provider_refund(order)

    order.refresh_from_db()

    from apps.notifications.services import notify

    notify(
        order.user,
        event="REFUND_ISSUED",
        title="Refund issued",
        body=f"{format_ghs(refund_amount)} has been returned to your VerifyGH wallet.",
        channels=("EMAIL", "IN_APP"),
        context={"amount": str(refund_amount), "reference": order.reference},
        metadata={"order_reference": order.reference},
    )
    record_audit(
        actor=actor, action="ORDER_REFUNDED", target=order,
        metadata={"amount": str(refund_amount), "reason": reason, "automatic": automatic,
                  "override_delivered": override_delivered},
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
