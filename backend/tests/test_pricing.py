"""The pricing engine: exact arithmetic, rule resolution and safety rails."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import Country, Provider, ProviderService, Service
from apps.common.errors import ServiceUnavailable
from apps.pricing.engine import NoPricingRule, quote_for_offering, resolve_rule
from apps.pricing.models import MarkupType, PricingRule, Rounding
from apps.pricing.rates import current_rate, record_rate

pytestmark = pytest.mark.django_db


@pytest.fixture
def offering(db):
    provider = Provider.objects.create(adapter_key="mock", name="Mock")
    service = Service.objects.create(slug="instagram", name="Instagram")
    country = Country.objects.create(code="US", name="United States", dial_code="+1")
    return ProviderService.objects.create(
        provider=provider,
        service=service,
        country=country,
        provider_service_code="instagram",
        cost_amount=Decimal("1.0000"),
        cost_currency="USD",
    )


def make_rule(**overrides) -> PricingRule:
    defaults = {
        "name": "Test rule",
        "markup_type": MarkupType.PERCENTAGE,
        "markup_percent": Decimal("20.00"),
        "markup_fixed": Decimal("0.00"),
        "payment_fee_percent": Decimal("0.00"),
        "risk_buffer_percent": Decimal("0.00"),
        "rounding": Rounding.NONE,
        "min_price": Decimal("0.50"),
        "max_price": Decimal("1000.00"),
        "priority": 100,
    }
    defaults.update(overrides)
    return PricingRule.objects.create(**defaults)


# ---------------------------------------------------------------------------
# The worked example from the specification
# ---------------------------------------------------------------------------


def test_the_specification_worked_example(offering, exchange_rate):
    """provider cost $1.00, rate 12.00, markup 20% -> GHS 14.40."""
    rule = make_rule()
    quote = quote_for_offering(offering, rule=rule)

    assert quote.provider_cost == Decimal("1.00")
    assert quote.exchange_rate == Decimal("12.000000")
    assert quote.base_cost == Decimal("12.00")
    assert quote.markup == Decimal("2.40")
    assert quote.customer_price == Decimal("14.40")
    assert quote.currency == "GHS"


def test_fees_and_buffer_stack_on_the_marked_up_subtotal(offering, exchange_rate):
    rule = make_rule(
        payment_fee_percent=Decimal("2.00"), risk_buffer_percent=Decimal("3.00")
    )
    quote = quote_for_offering(offering, rule=rule)

    # subtotal 14.40; fee 0.288 -> 0.29; buffer 0.432 -> 0.43
    assert quote.payment_fee == Decimal("0.29")
    assert quote.risk_buffer == Decimal("0.43")
    assert quote.customer_price == Decimal("15.12")


def test_fixed_markup(offering, exchange_rate):
    rule = make_rule(markup_type=MarkupType.FIXED, markup_fixed=Decimal("5.00"))
    assert quote_for_offering(offering, rule=rule).customer_price == Decimal("17.00")


def test_hybrid_markup(offering, exchange_rate):
    rule = make_rule(
        markup_type=MarkupType.HYBRID,
        markup_percent=Decimal("10.00"),
        markup_fixed=Decimal("2.00"),
    )
    # 12.00 + (1.20 + 2.00)
    assert quote_for_offering(offering, rule=rule).customer_price == Decimal("15.20")


@pytest.mark.parametrize(
    ("rounding", "expected"),
    [
        (Rounding.NONE, Decimal("14.40")),
        (Rounding.NEAREST_0_10, Decimal("14.40")),
        (Rounding.NEAREST_0_50, Decimal("14.50")),
        (Rounding.NEAREST_1_00, Decimal("14.00")),
        (Rounding.CEIL_1_00, Decimal("15.00")),
    ],
)
def test_rounding_modes(offering, exchange_rate, rounding, expected):
    rule = make_rule(rounding=rounding)
    assert quote_for_offering(offering, rule=rule).customer_price == expected


def test_price_is_clamped_to_the_configured_floor_and_ceiling(offering, exchange_rate):
    floor_rule = make_rule(min_price=Decimal("20.00"))
    assert quote_for_offering(offering, rule=floor_rule).customer_price == Decimal("20.00")

    # Cost is GHS 12.00 and the rule would charge 14.40; a ceiling between the
    # two clamps. (A ceiling below cost is refused - see test_marketplace.)
    ceiling_rule = make_rule(max_price=Decimal("13.00"), min_price=Decimal("1.00"))
    assert quote_for_offering(offering, rule=ceiling_rule).customer_price == Decimal("13.00")


def test_markup_and_gross_margin_are_reported_separately(offering, exchange_rate):
    """Cost 12.00, price 14.40: markup is 20% of cost, gross margin 16.67% of price."""
    quote = quote_for_offering(offering, rule=make_rule())
    assert quote.gross_profit == Decimal("2.40")
    assert quote.markup_percent_effective == Decimal("20.00")
    assert quote.gross_margin_percent == Decimal("16.67")


def test_quote_records_which_rule_and_rate_produced_it(offering, exchange_rate):
    rule = make_rule(name="Explainable")
    quote = quote_for_offering(offering, rule=rule)

    assert quote.pricing_rule_name == "Explainable"
    assert quote.exchange_rate_id == str(exchange_rate.id)
    assert quote.as_dict()["customer_price"] == "14.40"


# ---------------------------------------------------------------------------
# Rule resolution
# ---------------------------------------------------------------------------


def test_the_most_specific_rule_wins(offering, exchange_rate):
    make_rule(name="global", markup_percent=Decimal("10.00"), priority=100)
    make_rule(
        name="service", service=offering.service, markup_percent=Decimal("30.00"), priority=100
    )
    make_rule(
        name="service+country",
        service=offering.service,
        country=offering.country,
        markup_percent=Decimal("50.00"),
        priority=100,
    )

    resolved = resolve_rule(offering.service_id, offering.country_id)
    assert resolved.name == "service+country"
    assert quote_for_offering(offering).customer_price == Decimal("18.00")


def test_a_service_rule_beats_the_global_default(offering, exchange_rate):
    make_rule(name="global", markup_percent=Decimal("10.00"))
    make_rule(name="service", service=offering.service, markup_percent=Decimal("40.00"))

    assert resolve_rule(offering.service_id, offering.country_id).name == "service"


def test_inactive_rules_are_ignored(offering, exchange_rate):
    make_rule(name="global", markup_percent=Decimal("10.00"))
    make_rule(
        name="disabled", service=offering.service, markup_percent=Decimal("90.00"),
        is_active=False,
    )

    assert resolve_rule(offering.service_id, offering.country_id).name == "global"


def test_pricing_refuses_rather_than_guessing_when_no_rule_exists(offering, exchange_rate):
    with pytest.raises(NoPricingRule):
        quote_for_offering(offering)


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------


def test_no_exchange_rate_means_no_quote(offering):
    make_rule()
    with pytest.raises(ServiceUnavailable):
        quote_for_offering(offering)


def test_the_latest_rate_is_used(db):
    record_rate(Decimal("11.00"))
    record_rate(Decimal("13.50"))
    assert current_rate().rate == Decimal("13.500000")


def test_a_stale_rate_stops_quoting(db, offering, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.pricing.models import ExchangeRate

    rate = record_rate(Decimal("12.00"))
    ExchangeRate.objects.filter(pk=rate.pk).update(
        fetched_at=timezone.now() - timedelta(days=5)
    )
    make_rule()

    # Selling off a week-old cedi rate is worse than not selling.
    with pytest.raises(ServiceUnavailable) as exc:
        quote_for_offering(offering)
    assert exc.value.code == "STALE_EXCHANGE_RATE"


def test_rates_are_append_only(db):
    first = record_rate(Decimal("11.00"))
    second = record_rate(Decimal("12.00"))

    first.refresh_from_db()
    assert first.rate == Decimal("11.000000")
    assert second.rate == Decimal("12.000000")


# ---------------------------------------------------------------------------
# Bulk pricing
# ---------------------------------------------------------------------------


def test_bulk_pricing_matches_single_pricing(catalog):
    from apps.pricing.engine import quote_many

    offerings = list(ProviderService.objects.select_related("service", "country")[:10])
    bulk = quote_many(offerings)

    for item in offerings:
        assert bulk[str(item.pk)].customer_price == quote_for_offering(item).customer_price
