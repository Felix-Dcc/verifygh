"""The pricing engine.

    provider cost (USD)
      x exchange rate            -> base cost in GHS
      + markup                   -> our margin
      + payment fee              -> the MoMo collection fee we absorb
      + risk buffer              -> refunds and provider failures
      = raw price
      -> rounded, then clamped   = customer price
      -> never below cost        (unless the rule says otherwise)

Every quote returns its full breakdown. Admins see it in the service editor,
and the order stores it, so any historical price can be explained exactly.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from apps.catalog.models import ProviderService
from apps.common.errors import ServiceUnavailable
from apps.common.money import ZERO, quantize, round_to
from apps.pricing.models import MarkupType, PricingRule, Rounding
from apps.pricing.rates import current_rate

logger = logging.getLogger("verifygh.pricing")

HUNDRED = Decimal("100")

_ROUNDING_STEPS: dict[str, tuple[Decimal, bool]] = {
    Rounding.NONE: (Decimal("0.01"), False),
    Rounding.NEAREST_0_10: (Decimal("0.10"), False),
    Rounding.NEAREST_0_50: (Decimal("0.50"), False),
    Rounding.NEAREST_1_00: (Decimal("1.00"), False),
    Rounding.CEIL_1_00: (Decimal("1.00"), True),
}


@dataclass(frozen=True)
class Quote:
    """A fully-explained price. Frozen onto the order at purchase time."""

    customer_price: Decimal
    currency: str = "GHS"
    provider_cost: Decimal = ZERO
    provider_currency: str = "USD"
    exchange_rate: Decimal = ZERO
    exchange_rate_id: str = ""
    base_cost: Decimal = ZERO
    markup: Decimal = ZERO
    payment_fee: Decimal = ZERO
    risk_buffer: Decimal = ZERO
    raw_price: Decimal = ZERO
    pricing_rule_id: str = ""
    pricing_rule_name: str = ""
    applied: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        data = asdict(self)
        return {
            key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in data.items()
        }

    @property
    def margin(self) -> Decimal:
        return quantize(self.customer_price - self.base_cost)

    @property
    def margin_percent(self) -> Decimal:
        if self.base_cost <= ZERO:
            return ZERO
        return quantize((self.margin / self.base_cost) * HUNDRED)


class NoPricingRule(RuntimeError):
    """Raised when not even a global default rule exists."""


class PriceBelowCost(ServiceUnavailable):
    """The only price the rule allows would not cover what we pay for the number.

    Happens when a rule's maximum price sits below cost - usually because the
    provider's price jumped. The offering is not sold rather than sold at a
    loss; an admin fixes the rule, or marks it `allow_below_cost` on purpose.
    """

    code = "PRICE_UNAVAILABLE"
    message = "This service is not available at the moment. Please try again later."


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
    """The least a customer can pay and still cover what the number costs us.

    The provider's price in cedis, plus the collection fee on the money that
    pays for it. Selling below this loses money on every order.
    """
    return quantize(base_cost * (HUNDRED + payment_fee_percent) / HUNDRED)


def quote_for_offering(
    offering: ProviderService,
    *,
    rule: PricingRule | None = None,
    rate_row=None,
) -> Quote:
    """Price one provider offering for a customer.

    `rule` and `rate_row` may be passed in by `quote_many` so pricing a whole
    marketplace page stays a constant number of queries.
    """
    rule = rule or resolve_rule(offering.service_id, offering.country_id,
                                offering.provider_id)
    rate_row = rate_row or current_rate(base=offering.cost_currency, quote="GHS")

    provider_cost = Decimal(offering.cost_amount)
    rate = Decimal(rate_row.rate)
    base_cost = quantize(provider_cost * rate)

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

    clamped = min(max(rounded, quantize(rule.min_price)), quantize(rule.max_price))

    floor = cost_floor(base_cost, rule.payment_fee_percent)
    if clamped < floor and not rule.allow_below_cost:
        # Only the maximum price (or a negative fixed markup) can pull a price
        # under cost. Rounding the floor up keeps the price on the rule's grid.
        lifted = round_to(floor, step, ceiling=True)
        if lifted > quantize(rule.max_price):
            logger.warning(
                "price_below_cost_not_sold",
                extra={"offering": str(offering.pk), "floor": str(floor),
                       "max_price": str(rule.max_price)},
            )
            raise PriceBelowCost()
        clamped = lifted

    if clamped != rounded:
        logger.info(
            "price_clamped",
            extra={
                "offering": str(offering.pk),
                "rounded": str(rounded),
                "clamped": str(clamped),
            },
        )

    return Quote(
        customer_price=clamped,
        provider_cost=quantize(provider_cost),
        provider_currency=offering.cost_currency,
        exchange_rate=rate,
        exchange_rate_id=str(rate_row.id),
        base_cost=base_cost,
        markup=markup,
        payment_fee=payment_fee,
        risk_buffer=risk_buffer,
        raw_price=raw_price,
        pricing_rule_id=str(rule.id),
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
    )


def quote_many(offerings) -> dict[str, Quote]:
    """Price a list of offerings with one FX lookup and one rule query.

    The marketplace renders dozens of cards at once; this keeps that to a
    constant number of queries instead of one per card.
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

    # One FX lookup per distinct provider currency, not per offering.
    rate_rows = {
        currency: current_rate(base=currency, quote="GHS")
        for currency in {offering.cost_currency for offering in offerings}
    }

    quotes: dict[str, Quote] = {}
    for offering in offerings:
        try:
            quotes[str(offering.pk)] = quote_for_offering(
                offering,
                rule=pick(offering.service_id, offering.country_id, offering.provider_id),
                rate_row=rate_rows[offering.cost_currency],
            )
        except PriceBelowCost:
            # Left out of the result, so it is not listed; logged above.
            continue
    return quotes
