"""Number rentals: pricing, purchase, the inbox, cancelling and extending.

The same shape as apps/orders:

    1. check the customer may buy (the same checks as a verification)
    2. price on the server, from the provider's live price; never from the request
    3. move money inside a transaction, ledger first
    4. talk to the provider *outside* that transaction
    5. refund automatically when the provider gives the customer nothing

Two things differ from a verification. TextVerified's rental purchase takes no
`maxPrice`, so the price is read live just before charging and the customer is
told if it moved since they saw it. And the purchase is asynchronous upstream -
a sale that may still be "processing" - so a rental can sit in PENDING while
the sweep (apps/rentals/tasks.py) follows it up with the same idempotency key,
which never buys a second number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.services import record_audit
from apps.catalog.models import Provider, ProviderService, Service
from apps.common.errors import (
    AccountSuspended,
    Conflict,
    EmailNotVerified,
    LimitExceeded,
    NotFound,
    ProviderError,
    ServiceUnavailable,
    TermsNotAccepted,
    ValidationFailed,
)
from apps.common.ids import rental_reference
from apps.common.money import ZERO, format_ghs, quantize, round_to
from apps.rentals.models import (
    ALL_SERVICES,
    OPEN_RENTAL_STATUSES,
    ExtensionStatus,
    Rental,
    RentalExtension,
    RentalMessage,
    RentalStatus,
)
from apps.verification.base import RentalState
from apps.wallet.services import (
    WalletFrozen,
    charge_rental,
    get_or_create_wallet,
    net_spending,
    refund_rental_charge,
)

logger = logging.getLogger("verifygh.rentals")

#: Every length the provider sells, by days. What is *offered* is the
#: RENTAL_DURATIONS_DAYS setting, a subset of these.
KNOWN_DAYS = (1, 3, 7, 14, 30, 90, 365)

#: The rental page reads new messages at most this often while it is open.
LIVE_SYNC_SECONDS = 10
#: ...and the provider's word on whether it can still be cancelled, this often.
LIVE_REFRESH_SECONDS = 60

#: A rental's period is over by this long before it is closed without the
#: provider agreeing - a clock that disagrees must not keep it open forever.
EXPIRY_GRACE = timedelta(minutes=10)

#: At most one "a rental didn't go through" email per this many seconds.
RENTAL_FAILED_EMAIL_COOLDOWN = 10 * 60


def duration_label(days: int) -> str:
    if days == 365:
        return "1 year"
    return "1 day" if days == 1 else f"{days} days"


def offered_days() -> list[int]:
    days = []
    for raw in settings.VERIFYGH["RENTAL_DURATIONS_DAYS"]:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value in KNOWN_DAYS and value not in days:
            days.append(value)
    return sorted(days)


def valid_days(value) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 0
    if days not in offered_days():
        raise ValidationFailed("Choose one of the rental lengths on offer.",
                               details={"days": offered_days()})
    return days


# ---------------------------------------------------------------------------
# Who sells rentals
# ---------------------------------------------------------------------------


def _unavailable(message: str = "Number rentals are not available right now. "
                                "Please try again later.") -> ServiceUnavailable:
    return ServiceUnavailable(message, code="RENTALS_UNAVAILABLE")


def rental_provider() -> Provider:
    """The provider rentals are bought from: the active one, if it rents numbers.

    The same gate as a verification - enabled, a registered adapter, and a
    recorded resale authorisation - plus the adapter documenting rentals.
    """
    from apps.verification.registry import available_adapters, get_provider

    if not settings.VERIFYGH["RENTALS_ENABLED"]:
        raise _unavailable()
    key = settings.VERIFYGH["VERIFICATION_PROVIDER"]
    provider = Provider.objects.filter(adapter_key=key, is_enabled=True,
                                       resale_authorized=True).first()
    if provider is None or key not in available_adapters():
        raise _unavailable()
    if not get_provider(key).supports_rentals:
        raise _unavailable()
    return provider


def _client(provider: Provider):
    from apps.verification.registry import get_provider

    return get_provider(provider.adapter_key)


def rentable_services(provider: Provider):
    """Catalogue services a number can be rented for: those this provider sells."""
    offered = ProviderService.objects.filter(
        provider=provider, is_enabled=True,
    ).exclude(provider_service_code="").values("service_id")
    return (Service.objects.filter(id__in=offered, is_enabled=True, is_maintenance=False)
            .order_by("-is_popular", "popular_rank", "name"))


def resolve_target(provider: Provider, service_key: str) -> tuple[Service | None, str]:
    """(our service or None for "any app", the provider's name for it)."""
    key = str(service_key or "").strip().lower()
    if key in {"all", "any", ALL_SERVICES}:
        return None, ALL_SERVICES
    service = Service.objects.filter(slug=key).first()
    if service is None:
        raise NotFound("We do not offer that service.")
    if not service.is_enabled or service.is_maintenance:
        raise ServiceUnavailable("That service is not available right now.",
                                 code="SERVICE_DISABLED")
    offering = (ProviderService.objects
                .filter(provider=provider, service=service, is_enabled=True)
                .exclude(provider_service_code="")
                .order_by("country__display_order").first())
    if offering is None:
        raise ServiceUnavailable("Numbers for that app can't be rented yet.",
                                 code="RENTAL_NOT_OFFERED")
    return service, offering.provider_service_code


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RentalQuote:
    days: int
    price: Decimal
    provider_cost: Decimal
    provider_currency: str
    exchange_rate: Decimal
    breakdown: dict


def customer_price(provider_cost: Decimal, rate: Decimal) -> Decimal:
    """Provider price x Pricing FX rate x (100 + markup)%, rounded up to the step."""
    markup = Decimal(str(settings.VERIFYGH["RENTAL_MARKUP_PERCENT"]))
    step = Decimal(str(settings.VERIFYGH["RENTAL_PRICE_STEP"]))
    raw = Decimal(provider_cost) * Decimal(rate) * (Decimal("100") + markup) / Decimal("100")
    return round_to(raw, step, ceiling=True)


def _price_cache_key(provider: Provider, name: str, days: int) -> str:
    return f"rental-price:{provider.adapter_key}:{name.lower()}:{days}"


def quote(provider: Provider, name: str, days: int, *, fresh: bool = False) -> RentalQuote | None:
    """The customer price for renting `name` for `days`, or None if not sold.

    A listing reuses a price for RENTAL_PRICE_CACHE_SECONDS; a purchase passes
    `fresh` and asks the provider again, because the purchase call itself
    takes no price ceiling.
    """
    from apps.pricing.engine import pricing_fx

    key = _price_cache_key(provider, name, days)
    cached = None if fresh else cache.get(key)
    if cached is None:
        cost = _client(provider).rental_price(name, days)
        cached = "none" if cost is None else str(cost)
        cache.set(key, cached, int(settings.VERIFYGH["RENTAL_PRICE_CACHE_SECONDS"]))
    if cached == "none":
        return None

    cost = Decimal(cached)
    fx = pricing_fx("USD")
    price = customer_price(cost, fx.rate)
    if price <= ZERO:
        return None
    return RentalQuote(
        days=days, price=price, provider_cost=cost, provider_currency="USD",
        exchange_rate=fx.rate,
        breakdown={"provider_cost": str(cost), "provider_currency": "USD",
                   "exchange_rate": str(fx.rate), "fx_mode": fx.mode,
                   "markup_percent": str(settings.VERIFYGH["RENTAL_MARKUP_PERCENT"]),
                   "price_step": str(settings.VERIFYGH["RENTAL_PRICE_STEP"]),
                   "price": str(price)},
    )


def options(service_key: str) -> dict:
    """Every length on offer for one app (or any app), with its price."""
    provider = rental_provider()
    service, name = resolve_target(provider, service_key)
    durations = []
    for days in offered_days():
        entry = {"days": days, "label": duration_label(days), "price": None,
                 "available": False}
        try:
            priced = quote(provider, name, days)
        except (ProviderError, ServiceUnavailable):
            entry["note"] = "Price unavailable right now"
            durations.append(entry)
            continue
        if priced is not None:
            entry.update(price=str(priced.price), available=True)
        durations.append(entry)
    return {
        "service": service.slug if service else "all",
        "service_name": service.name if service else "Any app",
        "all_services": service is None,
        "currency": "GHS",
        "durations": durations,
    }


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _check_buyer(user) -> None:
    """The checks every rental purchase or extension shares with a verification."""
    from apps.common import maintenance

    if not settings.VERIFYGH["RENTALS_ENABLED"]:
        raise _unavailable()
    maintenance.require_buying_open()
    if user.is_suspended:
        raise AccountSuspended()
    if not user.has_accepted_current_terms:
        raise TermsNotAccepted()
    if settings.VERIFYGH["REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE"] and not user.is_email_verified:
        raise EmailNotVerified()


def check_rental_eligibility(user) -> None:
    _check_buyer(user)
    held = Rental.objects.filter(user=user, status__in=OPEN_RENTAL_STATUSES).count()
    limit = int(settings.VERIFYGH["RENTAL_MAX_ACTIVE"])
    if held >= limit:
        raise LimitExceeded(
            f"You already have {held} rented numbers. Let one end or cancel one first.",
            code="TOO_MANY_RENTALS",
        )


def _check_spend_cap(wallet, price: Decimal) -> None:
    spend_cap = quantize(settings.VERIFYGH["MAX_DAILY_SPEND"])
    spent_today = net_spending(wallet, created_at__gte=timezone.now() - timedelta(days=1))
    if spent_today + quantize(price) > spend_cap:
        raise LimitExceeded(
            f"This would take you past the daily spending limit of {format_ghs(spend_cap)}.",
            code="DAILY_SPEND_LIMIT",
        )


def _check_price(expected_price, priced: RentalQuote) -> None:
    """Refuse when the price moved since the customer saw it. Nothing is charged."""
    if expected_price in (None, ""):
        return
    try:
        expected = quantize(expected_price)
    except ValueError:
        raise ValidationFailed("The price sent is not a valid amount.") from None
    if expected != priced.price:
        raise Conflict(
            f"The price just changed to {format_ghs(priced.price)}. "
            "Please check it and try again - nothing was charged.",
            code="PRICE_CHANGED", details={"price": str(priced.price)},
        )


def _require_funding(provider: Provider, cost: Decimal, what: str) -> None:
    """Refuse before charging when our provider balance cannot pay for this.

    The same rule as apps/funding.check_funding, for a cost that is not a
    catalogue offering: unknown means yes, and a low reading is re-read once.
    """
    from apps.funding import services as funding
    from apps.funding.models import AlertKind, AlertSeverity, ProviderAccount

    if not settings.VERIFYGH["PROVIDER_FUNDING_GUARD"]:
        return
    account = ProviderAccount.objects.filter(provider=provider).first()
    if account is None or account.spendable is None or account.currency.upper() != "USD":
        return
    if account.spendable >= cost:
        return
    recently = account.last_sync_attempt_at and (
        timezone.now() - account.last_sync_attempt_at < funding.LIVE_RECHECK_INTERVAL)
    if not recently:
        account = funding.sync_balance(provider)
        if account.spendable is None or account.spendable >= cost:
            return
    funding.raise_alert(
        provider, AlertKind.PURCHASE_BLOCKED, AlertSeverity.CRITICAL,
        f"A customer could not rent a number: {provider.name} balance "
        f"USD {account.spendable} cannot cover {what}, which costs USD {cost}. Customers "
        "see \"temporarily unavailable\" until the balance is topped up.",
        metadata={"rental": what, "spendable": str(account.spendable), "required": str(cost)},
    )
    raise ServiceUnavailable(funding.CUSTOMER_UNAVAILABLE, code="TEMPORARILY_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------------------


def create_rental(*, user, service_key: str, days, expected_price=None,
                  idempotency_key: str, request=None) -> Rental:
    """Charge the wallet for a rental and record it as PENDING.

    The provider is asked for the number afterwards (`fulfil_rental`), once
    this transaction has committed.
    """
    existing = Rental.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing

    check_rental_eligibility(user)
    days = valid_days(days)
    provider = rental_provider()
    service, name = resolve_target(provider, service_key)
    label = service.name if service else "Any app"

    try:
        priced = quote(provider, name, days, fresh=True)
    except (ProviderError, ServiceUnavailable) as exc:
        logger.warning("rental_quote_failed", extra={"service": name[:60],
                                                     "error": exc.__class__.__name__})
        raise ServiceUnavailable(
            "Our number provider is not responding right now. Nothing was charged - "
            "please try again in a moment.", code="PROVIDER_UNAVAILABLE") from exc
    if priced is None:
        raise ServiceUnavailable(
            f"A {duration_label(days)} rental isn't available for {label} right now. "
            "Nothing was charged.", code="RENTAL_NOT_OFFERED")
    _check_price(expected_price, priced)

    try:
        in_stock = _client(provider).rental_stock(name, days)
    except (ProviderError, ServiceUnavailable) as exc:
        raise ServiceUnavailable(
            "Our number provider is not responding right now. Nothing was charged - "
            "please try again in a moment.", code="PROVIDER_UNAVAILABLE") from exc
    if in_stock <= 0:
        raise ServiceUnavailable(
            f"No {label} numbers are available to rent right now. Nothing was charged.",
            code="NO_AVAILABILITY")
    _require_funding(provider, priced.provider_cost, f"a {duration_label(days)} {label} rental")

    wallet = get_or_create_wallet(user)
    if wallet.is_frozen:
        raise WalletFrozen()
    _check_spend_cap(wallet, priced.price)

    try:
        with transaction.atomic():
            rental = Rental.objects.create(
                reference=rental_reference(),
                user=user,
                provider=provider,
                service=service,
                provider_service_name=name,
                days=days,
                price=priced.price,
                provider_cost=priced.provider_cost,
                provider_currency=priced.provider_currency,
                exchange_rate=priced.exchange_rate,
                price_breakdown=priced.breakdown,
                status=RentalStatus.PENDING,
                idempotency_key=idempotency_key,
                ip_address=getattr(request, "client_ip", None) or None,
            )
            charge = charge_rental(
                wallet=wallet, amount=priced.price, charge_id=rental.id,
                reference=rental.reference,
                description=f"{label} number rental, {duration_label(days)} ({rental.reference})",
            )
            Rental.objects.filter(pk=rental.pk).update(promo_amount=charge.promo,
                                                       cash_amount=charge.cash)
    except IntegrityError:
        duplicate = Rental.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if duplicate is not None:
            return duplicate
        raise

    rental.refresh_from_db()
    record_audit(actor=user, action="RENTAL_CREATED", target=rental, request=request,
                 metadata={"reference": rental.reference, "service": name, "days": days,
                           "price": str(rental.price)})
    logger.info("rental_created", extra={"rental": rental.reference, "service": name,
                                         "days": days, "price": str(rental.price)})
    return rental


def _is_refusal(exc: Exception) -> bool:
    """True when the provider definitely did nothing (so a refund is safe).

    A 4xx answer is a refusal - including "expired without completing", which
    is how TextVerified ends a purchase that never finished. A timeout, a 5xx,
    a 429 or 409 IdempotencyConflict ("still running") is not: the purchase
    may have happened, and the same key will tell us.
    """
    if isinstance(exc, ServiceUnavailable):
        # No call was made at all when the adapter is not configured.
        return getattr(exc, "code", "") == "PROVIDER_NOT_CONFIGURED"
    if str(getattr(exc, "provider_code", "") or "").lower() == "idempotencyconflict":
        return False
    status = int(getattr(exc, "http_status", 0) or 0)
    return 400 <= status < 500 and status not in (408, 409, 429)


def fulfil_rental(rental: Rental, *, give_up: bool = False) -> Rental:
    """Get the number from the provider, or refund.

    Safe to call repeatedly: every attempt sends the same idempotency key, and
    a purchase the provider is still processing is looked up by its sale.
    `give_up` (from the sweep, once RENTAL_PENDING_GIVE_UP_MINUTES have passed)
    refunds a rental that still has no answer.
    """
    if rental.status != RentalStatus.PENDING:
        return rental
    lock = f"rental-fulfil:{rental.pk}"
    if not cache.add(lock, 1, timeout=90):
        return rental
    try:
        return _fulfil(rental, give_up=give_up)
    finally:
        cache.delete(lock)


def _fulfil(rental: Rental, *, give_up: bool) -> Rental:
    provider = rental.provider
    if not (provider.is_enabled and provider.resale_authorized) and not rental.provider_sale_id:
        return fail_rental(rental, reason="Number rentals are temporarily unavailable.")

    Rental.objects.filter(pk=rental.pk).update(attempts=F("attempts") + 1)
    try:
        client = _client(provider)
        if rental.provider_sale_id:
            dto = client.get_rental_sale(rental.provider_sale_id)
        else:
            dto = client.create_rental(rental.provider_service_name, rental.days,
                                       idempotency_key=f"vgh-rental:{rental.id}")
    except (ProviderError, ServiceUnavailable, NotImplementedError) as exc:
        code = str(getattr(exc, "provider_code", "") or "")
        if rental.provider_sale_id and getattr(exc, "http_status", None) == 404:
            # Lost track of the sale: buying again with the same key answers
            # with the same sale, if there is one.
            Rental.objects.filter(pk=rental.pk).update(provider_sale_id="")
            rental.refresh_from_db()
            return rental
        if isinstance(exc, NotImplementedError) or _is_refusal(exc):
            logger.warning("rental_provider_refused", extra={"rental": rental.reference,
                                                             "provider_code": code})
            _note_provider_failure(provider, exc)
            return fail_rental(
                rental,
                reason=("No number was available just then." if code.lower() == "unavailable"
                        else "Our number provider could not supply a number."),
                staff_detail=(f"{provider.name} answered {code}." if code
                              else f"The call to {provider.name} failed "
                                   f"({exc.__class__.__name__})."),
            )
        logger.warning("rental_provider_unclear", extra={"rental": rental.reference,
                                                         "provider_code": code,
                                                         "error": exc.__class__.__name__})
        if give_up:
            return fail_rental(
                rental, reason="Our number provider did not confirm the number.",
                staff_detail=(f"No answer from {provider.name} after "
                              f"{settings.VERIFYGH['RENTAL_PENDING_GIVE_UP_MINUTES']} minutes. "
                              "Check its sales list for an unconfirmed rental."))
        rental.refresh_from_db()
        return rental
    return _apply(rental, dto, give_up=give_up)


def _note_provider_failure(provider: Provider, exc: Exception) -> None:
    try:
        from apps.funding.services import note_provider_failure

        note_provider_failure(provider, exc)
    except Exception:
        logger.exception("provider_failure_alert_failed")


def _apply(rental: Rental, dto, *, give_up: bool = False) -> Rental:
    cost = {"provider_cost": dto.cost} if dto.cost and dto.cost > 0 else {}
    if dto.state == RentalState.FAILED:
        return fail_rental(rental, reason="Our number provider could not supply a number.",
                           staff_detail=f"{rental.provider.name} reported the sale as failed.")
    if dto.state == RentalState.REFUNDED:
        return fail_rental(rental, reason="Our number provider could not supply a number.",
                           staff_detail=f"{rental.provider.name} refunded the rental at once.")
    if dto.state in (RentalState.PENDING, RentalState.UNKNOWN) or not dto.provider_rental_id:
        Rental.objects.filter(pk=rental.pk, status=RentalStatus.PENDING).update(
            provider_sale_id=dto.sale_id or rental.provider_sale_id, **cost)
        rental.refresh_from_db()
        if give_up:
            return fail_rental(
                rental, reason="Our number provider did not confirm the number.",
                staff_detail=(f"{rental.provider.name} was still processing sale "
                              f"{rental.provider_sale_id or '(none)'} after "
                              f"{settings.VERIFYGH['RENTAL_PENDING_GIVE_UP_MINUTES']} minutes."))
        return rental

    now = timezone.now()
    try:
        changed = Rental.objects.filter(pk=rental.pk, status=RentalStatus.PENDING).update(
            status=RentalStatus.ACTIVE,
            provider_rental_id=dto.provider_rental_id,
            provider_sale_id=dto.sale_id or rental.provider_sale_id,
            phone_number=dto.phone_number,
            activated_at=now,
            ends_at=dto.ends_at or now + timedelta(days=rental.days),
            can_refund=dto.can_refund,
            refundable_until=dto.refundable_until,
            **cost,
        )
    except IntegrityError:
        # Another of our rentals already holds this upstream rental. Never
        # attach it twice; staff must look.
        logger.error("rental_provider_id_collision", extra={"rental": rental.reference})
        rental.refresh_from_db()
        return rental
    rental.refresh_from_db()
    if changed != 1:
        return rental

    _warn_if_below_cost(rental)
    if dto.state == RentalState.EXPIRED:
        return expire_rental(rental)

    from apps.notifications.services import notify

    notify(rental.user, event="RENTAL_ACTIVE", title="Your rented number is ready",
           body=f"{rental.service_label}: {rental.phone_number}, for "
                f"{duration_label(rental.days)}.",
           channels=("IN_APP",), metadata={"rental_reference": rental.reference})
    logger.info("rental_active", extra={"rental": rental.reference})
    return rental


def _warn_if_below_cost(rental: Rental) -> None:
    try:
        cost_ghs = quantize(Decimal(rental.provider_cost) * Decimal(rental.exchange_rate))
    except (ArithmeticError, TypeError, ValueError):
        return
    if cost_ghs > quantize(rental.price):
        logger.error("rental_sold_below_cost", extra={
            "rental": rental.reference, "price": str(rental.price), "cost_ghs": str(cost_ghs)})


def _refund(rental: Rental, *, reason: str, new_status: str, from_status: str,
            detail_reason: str = "") -> bool:
    """Close the rental as `new_status` and return its price to the wallet.

    One transaction, guarded on the current status, so two workers cannot both
    refund it; the ledger keys make a replay of the credit a no-op as well.
    """
    amount = quantize(Decimal(rental.promo_amount) + Decimal(rental.cash_amount))
    wallet = get_or_create_wallet(rental.user)
    now = timezone.now()
    with transaction.atomic():
        changed = Rental.objects.filter(pk=rental.pk, status=from_status).update(
            status=new_status, ended_at=now,
            failure_reason=(detail_reason or rental.failure_reason)[:255],
            refunded_amount=amount, refunded_at=now if amount > ZERO else None,
        )
        if changed != 1:
            return False
        if amount > ZERO:
            refund_rental_charge(wallet=wallet, charge_id=rental.id, reference=rental.reference,
                                 promo=rental.promo_amount, cash=rental.cash_amount,
                                 reason=reason)
    rental.refresh_from_db()
    record_audit(action="RENTAL_REFUNDED", target=rental,
                 metadata={"reference": rental.reference, "amount": str(amount),
                           "reason": reason})
    return True


def fail_rental(rental: Rental, *, reason: str, staff_detail: str = "") -> Rental:
    """The provider gave the customer nothing: close it and refund in full."""
    if not _refund(rental, reason="provider_failed", new_status=RentalStatus.FAILED,
                   from_status=RentalStatus.PENDING, detail_reason=reason):
        rental.refresh_from_db()
        return rental

    from apps.notifications.services import notify

    notify(rental.user, event="RENTAL_FAILED", title="Your rental didn't go through",
           body=f"{reason} {format_ghs(rental.refunded_amount)} is back in your wallet.",
           channels=("IN_APP",), metadata={"rental_reference": rental.reference})
    _alert_staff_failed(rental, staff_detail or reason)
    logger.info("rental_failed", extra={"rental": rental.reference})
    return rental


def _alert_staff_failed(rental: Rental, detail: str) -> None:
    from apps.accounts.constants import AdminPermission
    from apps.accounts.services import mask_email
    from apps.notifications.staff import alert_staff

    try:
        alert_staff(
            permission=AdminPermission.ORDER_REFUND,
            event="STAFF_RENTAL_FAILED",
            title=f"Rental {rental.reference} didn't go through",
            body=(f"{rental.service_label}, {duration_label(rental.days)}, for "
                  f"{mask_email(rental.user.email)}. {detail} The customer was refunded "
                  f"{format_ghs(rental.refunded_amount)} automatically."),
            link=f"/admin/rentals?q={rental.reference}",
            reference=rental.reference,
            cooldown_key="staff-alert:rental-failed:email",
            cooldown_seconds=RENTAL_FAILED_EMAIL_COOLDOWN,
        )
    except Exception:
        logger.exception("staff_rental_failed_alert_failed", extra={"rental": rental.reference})


# ---------------------------------------------------------------------------
# The live rental
# ---------------------------------------------------------------------------


def sync_messages(rental: Rental, *, notify_customer: bool = True) -> int:
    """Store any new SMS the number received. Returns how many were new."""
    if rental.status != RentalStatus.ACTIVE or not rental.provider_rental_id:
        return 0
    try:
        received = _client(rental.provider).rental_messages(rental.provider_rental_id)
    except (ProviderError, ServiceUnavailable, NotImplementedError):
        logger.warning("rental_messages_failed", extra={"rental": rental.reference})
        return 0

    now = timezone.now()
    known = set(rental.messages.values_list("provider_message_id", flat=True))
    new = 0
    for message in received:
        if not message.provider_message_id or message.provider_message_id in known:
            continue
        try:
            with transaction.atomic():
                RentalMessage.objects.create(
                    rental=rental, provider_message_id=message.provider_message_id,
                    sender=message.sender[:64], body=message.body[:2000],
                    code=message.code[:32], received_at=message.received_at or now,
                )
        except IntegrityError:
            continue
        known.add(message.provider_message_id)
        new += 1
    Rental.objects.filter(pk=rental.pk).update(messages_checked_at=now)

    if new and notify_customer:
        from apps.notifications.services import notify

        # The text and the code stay out of the notification: it is only a nudge.
        notify(rental.user, event="RENTAL_MESSAGE", title="New message on your rented number",
               body=(f"{rental.service_label} number {rental.phone_number}: "
                     + ("1 new message." if new == 1 else f"{new} new messages.")),
               channels=("IN_APP",), metadata={"rental_reference": rental.reference})
    if new:
        logger.info("rental_messages_received", extra={"rental": rental.reference, "new": new})
    return new


def refresh_rental(rental: Rental) -> Rental:
    """Read the rental back from the provider and catch up with what it says."""
    if rental.status != RentalStatus.ACTIVE or not rental.provider_rental_id:
        return rental
    try:
        dto = _client(rental.provider).get_rental(rental.provider_rental_id)
    except (ProviderError, ServiceUnavailable, NotImplementedError):
        logger.warning("rental_refresh_failed", extra={"rental": rental.reference})
        return rental

    if dto.state == RentalState.EXPIRED:
        return expire_rental(rental)
    if dto.state == RentalState.REFUNDED:
        # Refunded upstream without us asking (the provider took the number
        # back): we were refunded, so the customer is too.
        logger.warning("rental_refunded_upstream", extra={"rental": rental.reference})
        if _refund(rental, reason="provider_refunded", new_status=RentalStatus.REFUNDED,
                   from_status=RentalStatus.ACTIVE,
                   detail_reason="Our number provider ended this rental."):
            from apps.notifications.services import notify

            notify(rental.user, event="RENTAL_REFUNDED", title="Your rental was refunded",
                   body=(f"Our provider ended your {rental.service_label} number "
                         f"{rental.phone_number}. {format_ghs(rental.refunded_amount)} is "
                         "back in your wallet."),
                   channels=("IN_APP", "EMAIL"),
                   metadata={"rental_reference": rental.reference})
        return rental
    if dto.state == RentalState.ACTIVE:
        updates = {"can_refund": dto.can_refund, "refundable_until": dto.refundable_until}
        if dto.ends_at:
            updates["ends_at"] = dto.ends_at
        Rental.objects.filter(pk=rental.pk, status=RentalStatus.ACTIVE).update(**updates)
        rental.refresh_from_db()
    return rental


def expire_rental(rental: Rental) -> Rental:
    """The period is over: read the last messages, then close it. No refund."""
    if rental.status != RentalStatus.ACTIVE:
        return rental
    sync_messages(rental)
    changed = Rental.objects.filter(pk=rental.pk, status=RentalStatus.ACTIVE).update(
        status=RentalStatus.EXPIRED, ended_at=timezone.now(), can_refund=False)
    rental.refresh_from_db()
    if changed == 1:
        from apps.notifications.services import notify

        notify(rental.user, event="RENTAL_ENDED", title="Your rented number has ended",
               body=(f"{rental.service_label} number {rental.phone_number} no longer "
                     "receives messages."),
               channels=("IN_APP",), metadata={"rental_reference": rental.reference})
        logger.info("rental_expired", extra={"rental": rental.reference})
    return rental


def cancel_blocker(rental: Rental) -> str:
    """Why the customer cannot cancel for a refund now, or "" (as last read)."""
    if rental.status != RentalStatus.ACTIVE:
        return "Only an active rental can be cancelled."
    if not rental.can_refund:
        return "Our provider no longer allows this rental to be cancelled."
    if rental.refundable_until and rental.refundable_until <= timezone.now():
        return "The time to cancel this rental has passed."
    return ""


def cancel_rental(rental: Rental, *, actor, request=None) -> Rental:
    """Cancel and refund in full, while - and only while - the provider allows it.

    The provider is asked live first (its `canRefund`), then asked to refund;
    only when it accepts is the customer's money returned. An extension is not
    refundable (the provider says so) and is not returned.
    """
    lock = f"rental-cancel:{rental.pk}"
    if not cache.add(lock, 1, timeout=60):
        raise Conflict("This rental is already being cancelled.", code="RENTAL_BUSY")
    try:
        if rental.status != RentalStatus.ACTIVE:
            raise Conflict("Only an active rental can be cancelled.",
                           code="RENTAL_NOT_REFUNDABLE")
        rental = refresh_rental(rental)
        blocker = cancel_blocker(rental)
        if blocker:
            raise Conflict(blocker, code="RENTAL_NOT_REFUNDABLE")
        try:
            accepted = _client(rental.provider).refund_rental(rental.provider_rental_id)
        except (ProviderError, ServiceUnavailable) as exc:
            raise ServiceUnavailable(
                "We couldn't reach our number provider to cancel this. Please try again "
                "in a moment.", code="PROVIDER_UNAVAILABLE") from exc
        if not accepted:
            Rental.objects.filter(pk=rental.pk).update(can_refund=False)
            raise Conflict("Our provider no longer allows this rental to be cancelled.",
                           code="RENTAL_NOT_REFUNDABLE")

        if not _refund(rental, reason="customer_cancelled", new_status=RentalStatus.REFUNDED,
                       from_status=RentalStatus.ACTIVE,
                       detail_reason="Cancelled at your request."):
            rental.refresh_from_db()
            return rental
    finally:
        cache.delete(lock)

    from apps.notifications.services import notify

    notify(rental.user, event="RENTAL_REFUNDED", title="Rental cancelled",
           body=(f"Your {rental.service_label} number {rental.phone_number} was cancelled. "
                 f"{format_ghs(rental.refunded_amount)} is back in your wallet."),
           channels=("IN_APP", "EMAIL"), metadata={"rental_reference": rental.reference})
    record_audit(actor=actor, action="RENTAL_CANCELLED", target=rental, request=request,
                 metadata={"reference": rental.reference,
                           "refunded": str(rental.refunded_amount)})
    logger.info("rental_cancelled", extra={"rental": rental.reference})
    return rental


# ---------------------------------------------------------------------------
# Extending
# ---------------------------------------------------------------------------


def extension_quote(rental: Rental, days) -> RentalQuote:
    """The price of adding `days` to this rental: what renting it that long costs."""
    days = valid_days(days)
    if rental.status != RentalStatus.ACTIVE:
        raise Conflict("Only an active rental can be extended.", code="RENTAL_NOT_ACTIVE")
    try:
        priced = quote(rental.provider, rental.provider_service_name, days)
    except (ProviderError, ServiceUnavailable) as exc:
        raise ServiceUnavailable("Our number provider is not responding right now. Please "
                                 "try again in a moment.", code="PROVIDER_UNAVAILABLE") from exc
    if priced is None:
        raise Conflict(f"This number can't be extended by {duration_label(days)}.",
                       code="EXTENSION_NOT_OFFERED")
    return priced


def extend_rental(rental: Rental, *, user, days, expected_price=None,
                  idempotency_key: str, request=None) -> RentalExtension:
    """Charge for more days, then ask the provider to add them.

    Refunded automatically if the provider refuses. If its answer is lost, the
    extension stays PENDING and the sweep settles it by reading the rental's
    end date back - extensions carry no idempotency key upstream, so they are
    never simply sent again.
    """
    existing = RentalExtension.objects.filter(rental=rental,
                                              idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if rental.user_id != user.id:
        raise NotFound("We could not find that rental.")

    lock = f"rental-extend:{rental.pk}"
    if not cache.add(lock, 1, timeout=90):
        raise Conflict("This rental is already being extended.", code="RENTAL_BUSY")
    try:
        _check_buyer(user)
        rental.refresh_from_db()
        if rental.status != RentalStatus.ACTIVE or not rental.provider_rental_id:
            raise Conflict("Only an active rental can be extended.", code="RENTAL_NOT_ACTIVE")
        if not rental.ends_at or rental.ends_at <= timezone.now() + timedelta(minutes=2):
            raise Conflict("This rental is about to end and can no longer be extended.",
                           code="RENTAL_NOT_ACTIVE")
        if rental.extensions.filter(status=ExtensionStatus.PENDING).exists():
            raise Conflict("An extension of this rental is still being confirmed.",
                           code="RENTAL_BUSY")
        days = valid_days(days)
        try:
            priced = quote(rental.provider, rental.provider_service_name, days, fresh=True)
        except (ProviderError, ServiceUnavailable) as exc:
            raise ServiceUnavailable(
                "Our number provider is not responding right now. Nothing was charged - "
                "please try again in a moment.", code="PROVIDER_UNAVAILABLE") from exc
        if priced is None:
            raise Conflict(f"This number can't be extended by {duration_label(days)}.",
                           code="EXTENSION_NOT_OFFERED")
        _check_price(expected_price, priced)
        _require_funding(rental.provider, priced.provider_cost,
                         f"a {duration_label(days)} extension of {rental.reference}")

        wallet = get_or_create_wallet(user)
        if wallet.is_frozen:
            raise WalletFrozen()
        _check_spend_cap(wallet, priced.price)

        try:
            with transaction.atomic():
                extension = RentalExtension.objects.create(
                    rental=rental, days=days, price=priced.price,
                    provider_cost=priced.provider_cost, exchange_rate=priced.exchange_rate,
                    previous_ends_at=rental.ends_at, idempotency_key=idempotency_key,
                )
                charge = charge_rental(
                    wallet=wallet, amount=priced.price, charge_id=extension.id,
                    reference=rental.reference,
                    description=(f"{rental.service_label} number rental extended by "
                                 f"{duration_label(days)} ({rental.reference})"),
                )
                RentalExtension.objects.filter(pk=extension.pk).update(
                    promo_amount=charge.promo, cash_amount=charge.cash)
        except IntegrityError:
            duplicate = RentalExtension.objects.filter(
                rental=rental, idempotency_key=idempotency_key).first()
            if duplicate is not None:
                return duplicate
            raise
        extension.refresh_from_db()

        try:
            dto = _client(rental.provider).extend_rental(rental.provider_rental_id, days)
        except (ProviderError, ServiceUnavailable, NotImplementedError) as exc:
            if isinstance(exc, NotImplementedError) or _is_refusal(exc):
                logger.warning("rental_extension_refused",
                               extra={"rental": rental.reference,
                                      "provider_code": str(getattr(exc, "provider_code", ""))})
                return _fail_extension(extension)
            logger.warning("rental_extension_unclear", extra={"rental": rental.reference})
            return settle_extension(extension)
        return _complete_extension(extension, new_ends_at=dto.new_ends_at, cost=dto.cost,
                                   provider_extension_id=dto.provider_extension_id,
                                   request=request)
    finally:
        cache.delete(lock)


def _complete_extension(extension: RentalExtension, *, new_ends_at, cost=None,
                        provider_extension_id: str = "", request=None) -> RentalExtension:
    rental = extension.rental
    new_ends_at = new_ends_at or (extension.previous_ends_at or timezone.now()) + timedelta(
        days=extension.days)
    updates = {"status": ExtensionStatus.COMPLETED, "new_ends_at": new_ends_at,
               "provider_extension_id": provider_extension_id[:128]}
    if cost and cost > 0:
        updates["provider_cost"] = cost
    with transaction.atomic():
        changed = RentalExtension.objects.filter(
            pk=extension.pk, status=ExtensionStatus.PENDING).update(**updates)
        if changed == 1:
            # The reminder fires again before the new end.
            Rental.objects.filter(pk=rental.pk).update(ends_at=new_ends_at,
                                                       expiry_notified_at=None)
    extension.refresh_from_db()
    if changed != 1:
        return extension
    rental.refresh_from_db()

    from apps.notifications.services import notify

    notify(rental.user, event="RENTAL_EXTENDED", title="Rental extended",
           body=(f"Your {rental.service_label} number {rental.phone_number} now runs "
                 f"{duration_label(extension.days)} longer."),
           channels=("IN_APP",), metadata={"rental_reference": rental.reference})
    record_audit(actor=rental.user, action="RENTAL_EXTENDED", target=rental, request=request,
                 metadata={"reference": rental.reference, "days": extension.days,
                           "price": str(extension.price)})
    try:
        cost_ghs = quantize(Decimal(extension.provider_cost) * Decimal(extension.exchange_rate))
        if cost_ghs > quantize(extension.price):
            logger.error("rental_extension_below_cost", extra={
                "rental": rental.reference, "price": str(extension.price),
                "cost_ghs": str(cost_ghs)})
    except (ArithmeticError, TypeError, ValueError):
        pass
    return extension


def _fail_extension(extension: RentalExtension) -> RentalExtension:
    rental = extension.rental
    wallet = get_or_create_wallet(rental.user)
    with transaction.atomic():
        changed = RentalExtension.objects.filter(
            pk=extension.pk, status=ExtensionStatus.PENDING).update(
            status=ExtensionStatus.FAILED)
        if changed == 1:
            refund_rental_charge(wallet=wallet, charge_id=extension.id,
                                 reference=rental.reference, promo=extension.promo_amount,
                                 cash=extension.cash_amount, reason="extension_failed")
    extension.refresh_from_db()
    if changed == 1:
        from apps.notifications.services import notify

        notify(rental.user, event="RENTAL_EXTENSION_FAILED",
               title="Your rental couldn't be extended",
               body=(f"Our provider couldn't extend {rental.reference}. "
                     f"{format_ghs(extension.price)} is back in your wallet."),
               channels=("IN_APP",), metadata={"rental_reference": rental.reference})
    return extension


def settle_extension(extension: RentalExtension, *, give_up: bool = False) -> RentalExtension:
    """Decide an extension whose answer was lost, from the rental's end date."""
    if extension.status != ExtensionStatus.PENDING:
        return extension
    rental = extension.rental
    try:
        dto = _client(rental.provider).get_rental(rental.provider_rental_id)
    except (ProviderError, ServiceUnavailable, NotImplementedError):
        dto = None
    previous = extension.previous_ends_at
    if dto is not None and dto.ends_at and previous and \
            dto.ends_at >= previous + timedelta(days=extension.days) - timedelta(hours=1):
        return _complete_extension(extension, new_ends_at=dto.ends_at)
    if give_up or (dto is not None and dto.state in (RentalState.EXPIRED,
                                                     RentalState.REFUNDED)):
        return _fail_extension(extension)
    return extension
