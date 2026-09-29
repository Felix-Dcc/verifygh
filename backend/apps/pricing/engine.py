"""The pricing engine: from what a number costs us to what a customer pays.

    provider cost (provider's currency, from its API or entered by staff)
      x VerifyGH Pricing FX Rate          -> cost in cedis
      + markup (percent, fixed, or both)  -> our margin
      + collection fee %, risk buffer %   -> costs a rule may add on top
      = raw price
      -> rounded, kept within the rule's min/max, never below cost
      = calculated price
      -> staff override, if one is set    = recommended price
      -> published price (review mode)    = customer price

Every quote carries every step, the order stores the whole quote, and the
admin sees the same breakdown - so any price, past or present, can be
explained exactly.

Words matter here and are used consistently:

* **Markup %** is profit divided by *cost*: what a rule adds.
* **Gross margin %** is profit divided by *price*: what share of each sale we
  keep. Cost 8, price 10: markup 25%, gross margin 20%. They are never the
  same number and never share a label.
* **Gross profit** is price minus the provider cost in cedis.

Nothing here is specific to one provider: an offering is whichever provider
supplies a (service, country), and its cost, currency and rules are resolved
the same way for every one.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from apps.catalog.models import ProviderService
from apps.common.errors import ServiceUnavailable
from apps.common.money import ZERO, quantize, round_to
from apps.pricing.models import FXMode, MarkupType, PriceOverride, PricingFXRate, PricingPolicy, PricingRule, Rounding
from apps.pricing.rates import current_rate, latest_rate_row

logger = logging.getLogger("verifygh.pricing")

HUNDRED = Decimal("100")
SIX_PLACES = Decimal("0.000001")

_ROUNDING_STEPS: dict[str, tuple[Decimal, bool]] = {
    Rounding.NONE: (Decimal("0.01"), False),
    Rounding.NEAREST_0_10: (Decimal("0.10"), False),
    Rounding.NEAREST_0_50: (Decimal("0.50"), False),
    Rounding.NEAREST_1_00: (Decimal("1.00"), False),
    Rounding.CEIL_1_00: (Decimal("1.00"), True),
}

_UNSET = object()


class NoPricingRule(RuntimeError):
    """Raised when not even a global default rule exists."""


class PriceBelowCost(ServiceUnavailable):
    """The price would not cover what the number costs us, and nothing says
    that is deliberate. The offering is not sold rather than sold at a loss."""

    code = "PRICE_UNAVAILABLE"
    message = "This service is not available at the moment. Please try again later."


class CostUnknown(ServiceUnavailable):
    """We do not know what the provider charges for this offering yet."""

    code = "PRICE_UNAVAILABLE"
    message = "This service is not available at the moment. Please try again later."


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FX:
    """The VerifyGH Pricing FX Rate for one currency, and where it came from."""

    currency: str
    rate: Decimal
    #: MANUAL, AUTOMATIC, or MARKET (no pricing rate configured: the market
    #: rate is used as it is).
    mode: str
    market_rate: Decimal | None = None
    market_rate_id: str = ""
    adjustment_percent: Decimal = ZERO


def pricing_fx(currency: str = "USD") -> FX:
    """The rate provider costs in `currency` are priced at. Raises rather than guess."""
    currency = currency.upper()
    if currency == "GHS":
        return FX(currency, Decimal("1"), FXMode.MANUAL)
    config = PricingFXRate.objects.filter(base_currency=currency).first()
    market = latest_rate_row(currency, "GHS")

    if config is not None and config.mode == FXMode.MANUAL:
        if not config.manual_rate:
            raise ServiceUnavailable(
                "Pricing is temporarily unavailable. Please try again shortly.",
                code="NO_EXCHANGE_RATE",
            )
        return FX(currency, Decimal(config.manual_rate), FXMode.MANUAL,
                  Decimal(market.rate) if market else None, str(market.id) if market else "")

    # Automatic, or not configured at all: the market rate, which must be fresh.
    row = current_rate(currency, "GHS")
    adjustment = Decimal(config.adjustment_percent) if config else ZERO
    rate = (Decimal(row.rate) * (HUNDRED + adjustment) / HUNDRED).quantize(SIX_PLACES)
    return FX(currency, rate, FXMode.AUTOMATIC if config else "MARKET", Decimal(row.rate),
              str(row.id), adjustment)


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quote:
    """A fully explained price. Frozen onto the order at purchase time."""

    customer_price: Decimal
    currency: str = "GHS"
    provider_cost: Decimal = ZERO
    provider_currency: str = "USD"
    cost_source: str = ""
    #: The VerifyGH Pricing FX Rate used (kept under this name: orders store it).
    exchange_rate: Decimal = ZERO
    exchange_rate_id: str = ""
    market_rate: Decimal | None = None
    fx_mode: str = ""
    fx_adjustment_percent: Decimal = ZERO
    base_cost: Decimal = ZERO
    markup: Decimal = ZERO
    payment_fee: Decimal = ZERO
    risk_buffer: Decimal = ZERO
    raw_price: Decimal = ZERO
    calculated_price: Decimal = ZERO
    override_price: Decimal | None = None
    override_id: str = ""
    override_reason: str = ""
    recommended_price: Decimal = ZERO
    published_price: Decimal | None = None
    pending_review: bool = False
    below_minimum_margin: bool = False
    minimum_margin_percent: Decimal = ZERO
    pricing_rule_id: str = ""
    pricing_rule_name: str = ""
    applied: dict = field(default_factory=dict)
    quoted_at: datetime | None = None

    # -- what the business earns -------------------------------------------

    @property
    def gross_profit(self) -> Decimal:
        return quantize(self.customer_price - self.base_cost)

    @property
    def gross_margin_percent(self) -> Decimal:
        """Profit as a share of the price the customer pays."""
        if self.customer_price <= ZERO:
            return ZERO
        return quantize(self.gross_profit / self.customer_price * HUNDRED)

    @property
    def markup_percent_effective(self) -> Decimal:
        """Profit as a share of what the number costs us."""
        if self.base_cost <= ZERO:
            return ZERO
        return quantize(self.gross_profit / self.base_cost * HUNDRED)

    @property
    def is_loss(self) -> bool:
        return self.customer_price < self.base_cost

    # Kept for older callers: `margin` has always meant gross profit.
    @property
    def margin(self) -> Decimal:
        return self.gross_profit

    def as_dict(self) -> dict:
        data = asdict(self)
        data.update(
            gross_profit=self.gross_profit,
            gross_margin_percent=self.gross_margin_percent,
            markup_percent_effective=self.markup_percent_effective,
            is_loss=self.is_loss,
        )

        def plain(value):
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        return {key: plain(value) for key, value in data.items()}


# ---------------------------------------------------------------------------
# Rule resolution
# ---------------------------------------------------------------------------


def resolve_rule(service_id=None, country_id=None, provider_id=None) -> PricingRule:
    """Most-specific-active-rule wins: the more of service, country and provider a
    rule names, the more specific it is; priority breaks ties."""
    candidates = list(
        PricingRule.objects.filter(is_active=True).filter(
            models_q(service_id, country_id, provider_id)
        ).order_by("priority", "-created_at")
    )
    if not candidates:
        raise NoPricingRule(
            "No active pricing rule matches, and no global default exists. "
            "Create one before selling anything."
        )
    candidates.sort(key=lambda rule: (-rule.specificity, rule.priority))
    return candidates[0]


def models_q(service_id, country_id, provider_id=None):
    from django.db.models import Q

    return (
        (Q(service_id=service_id) | Q(service__isnull=True))
        & (Q(country_id=country_id) | Q(country__isnull=True))
        & (Q(provider_id=provider_id) | Q(provider__isnull=True))
    )


def cost_floor(base_cost: Decimal, payment_fee_percent: Decimal) -> Decimal:
    """The least a rule-calculated price may be: provider cost in cedis plus the
    collection fee on the money that pays for it."""
    return quantize(base_cost * (HUNDRED + payment_fee_percent) / HUNDRED)


def active_override(offering) -> PriceOverride | None:
    return PriceOverride.objects.filter(offering=offering, is_active=True).first()


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


def quote_for_offering(
    offering: ProviderService,
    *,
    rule: PricingRule | None = None,
    rate_row=None,
    fx: FX | None = None,
    override=_UNSET,
    policy: PricingPolicy | None = None,
    published: bool = True,
) -> Quote:
    """Price one offering.

    `published=True` (the default) is what the customer pays: the published
    price when prices are reviewed before publishing. `published=False` is what
    the engine recommends right now - what the admin reviews and previews.

    `rule`, `fx`, `override` and `policy` may be passed in by `quote_many` so a
    whole marketplace page prices in a constant number of queries, or by the
    admin preview to try settings before saving them. `rate_row` is accepted
    for older callers and ignored.
    """
    provider_cost = Decimal(offering.cost_amount or 0)
    if provider_cost <= ZERO:
        raise CostUnknown()

    rule = rule or resolve_rule(offering.service_id, offering.country_id, offering.provider_id)
    fx = fx or pricing_fx(offering.cost_currency)
    policy = policy or PricingPolicy.get()
    if override is _UNSET:
        override = active_override(offering)

    base_cost = quantize(provider_cost * fx.rate)

    if rule.markup_type == MarkupType.PERCENTAGE:
        markup = quantize(base_cost * rule.markup_percent / HUNDRED)
    elif rule.markup_type == MarkupType.FIXED:
        markup = quantize(rule.markup_fixed)
    else:  # HYBRID
        markup = quantize(base_cost * rule.markup_percent / HUNDRED + rule.markup_fixed)

    subtotal = base_cost + markup
    payment_fee = quantize(subtotal * rule.payment_fee_percent / HUNDRED)
    risk_buffer = quantize(subtotal * rule.risk_buffer_percent / HUNDRED)
    raw_price = quantize(subtotal + payment_fee + risk_buffer)

    step, ceiling = _ROUNDING_STEPS.get(rule.rounding, (Decimal("0.01"), False))
    rounded = round_to(raw_price, step, ceiling=ceiling)
    calculated = min(max(rounded, quantize(rule.min_price)), quantize(rule.max_price))

    floor = cost_floor(base_cost, rule.payment_fee_percent)
    if calculated < floor and not rule.allow_below_cost:
        # Only the maximum price (or a negative fixed markup) pulls a rule's
        # price under cost. Rounding the floor up keeps it on the rule's grid.
        lifted = round_to(floor, step, ceiling=True)
        if lifted > quantize(rule.max_price):
            logger.warning(
                "price_below_cost_not_sold",
                extra={"offering": str(offering.pk), "floor": str(floor),
                       "max_price": str(rule.max_price)},
            )
            raise PriceBelowCost()
        calculated = lifted

    recommended = quantize(override.price) if override is not None else calculated

    published_price = offering.customer_price
    if published and not policy.auto_publish_prices and published_price is not None:
        customer_price = quantize(published_price)
    else:
        customer_price = recommended
    pending = (not policy.auto_publish_prices and published_price is not None
               and quantize(published_price) != recommended)

    # Never sell below cost by accident. An override may, but only one that
    # says so; a rule may, but only one marked to; anything else - including a
    # published price the provider's cost has since overtaken - is not sold
    # until someone looks at it.
    loss_allowed = (
        (override is not None and override.allow_loss and customer_price == recommended)
        or (override is None and rule.allow_below_cost)
    )
    if customer_price < base_cost and not loss_allowed:
        logger.warning("loss_making_price_not_sold",
                       extra={"offering": str(offering.pk), "price": str(customer_price),
                              "cost": str(base_cost)})
        raise PriceBelowCost()

    quote = Quote(
        customer_price=customer_price,
        provider_cost=quantize_cost(provider_cost),
        provider_currency=offering.cost_currency,
        cost_source=getattr(offering, "cost_source", ""),
        exchange_rate=fx.rate,
        exchange_rate_id=fx.market_rate_id,
        market_rate=fx.market_rate,
        fx_mode=fx.mode,
        fx_adjustment_percent=fx.adjustment_percent,
        base_cost=base_cost,
        markup=markup,
        payment_fee=payment_fee,
        risk_buffer=risk_buffer,
        raw_price=raw_price,
        calculated_price=calculated,
        override_price=quantize(override.price) if override is not None else None,
        override_id=str(override.pk) if override is not None else "",
        override_reason=override.reason if override is not None else "",
        recommended_price=recommended,
        published_price=quantize(published_price) if published_price is not None else None,
        pending_review=pending,
        minimum_margin_percent=Decimal(policy.minimum_margin_percent),
        pricing_rule_id=str(rule.id) if rule.pk else "",
        pricing_rule_name=rule.name,
        applied={
            "markup_type": rule.markup_type,
            "markup_percent": str(rule.markup_percent),
            "markup_fixed": str(rule.markup_fixed),
            "payment_fee_percent": str(rule.payment_fee_percent),
            "risk_buffer_percent": str(rule.risk_buffer_percent),
            "rounding": rule.rounding,
            "min_price": str(rule.min_price),
            "max_price": str(rule.max_price),
            "allow_below_cost": rule.allow_below_cost,
            "cost_floor": str(floor),
        },
        quoted_at=timezone.now(),
    )
    below = quote.gross_margin_percent < Decimal(policy.minimum_margin_percent)
    return Quote(**{**_fields(quote), "below_minimum_margin": below})


def quantize_cost(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"))


def _fields(quote: Quote) -> dict:
    return {name: getattr(quote, name) for name in Quote.__dataclass_fields__}


def quote_many(offerings, *, published: bool = True) -> dict[str, Quote]:
    """Price a list of offerings with a constant number of queries.

    Offerings that cannot be sold - cost unknown, or only sellable at a loss
    nobody approved - are left out of the result rather than failing the batch.
    """
    offerings = list(offerings)
    if not offerings:
        return {}

    rules = list(PricingRule.objects.filter(is_active=True).order_by("priority", "-created_at"))
    if not rules:
        raise NoPricingRule("No active pricing rule exists.")

    def pick(service_id, country_id, provider_id) -> PricingRule:
        matches = [
            rule
            for rule in rules
            if (rule.service_id in (None, service_id))
            and (rule.country_id in (None, country_id))
            and (rule.provider_id in (None, provider_id))
        ]
        matches.sort(key=lambda rule: (-rule.specificity, rule.priority))
        if not matches:
            raise NoPricingRule("No active pricing rule matches this service and country.")
        return matches[0]

    fx_by_currency = {
        currency: pricing_fx(currency)
        for currency in {offering.cost_currency for offering in offerings}
    }
    overrides = {
        o.offering_id: o
        for o in PriceOverride.objects.filter(
            is_active=True, offering_id__in=[offering.pk for offering in offerings]
        )
    }
    policy = PricingPolicy.get()

    quotes: dict[str, Quote] = {}
    for offering in offerings:
        try:
            quotes[str(offering.pk)] = quote_for_offering(
                offering,
                rule=pick(offering.service_id, offering.country_id, offering.provider_id),
                fx=fx_by_currency[offering.cost_currency],
                override=overrides.get(offering.pk),
                policy=policy,
                published=published,
            )
        except (PriceBelowCost, CostUnknown):
            continue
    return quotes
