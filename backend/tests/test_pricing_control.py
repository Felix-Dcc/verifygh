"""Admin control over pricing: provider cost -> pricing FX -> markup -> price.

Uses the worked example from the pricing brief throughout: a $0.50 provider
cost, a GHS 15.20 VerifyGH Pricing FX Rate and a 25% markup make a GHS 7.60
cost and a GHS 9.50 price - GHS 1.90 gross profit, a 25% markup but a 20%
gross margin.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.catalog.models import ProviderService
from apps.catalog.services import sync_catalog
from apps.orders.models import Order
from apps.pricing.engine import PriceBelowCost, pricing_fx, quote_for_offering
from apps.pricing.models import (
    ExchangeRate,
    MarkupType,
    PriceChange,
    PriceChangeSource,
    PricingFXRate,
    PricingPolicy,
    PricingRule,
    ProviderCostChange,
    Rounding,
)
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

P = "/api/v1/admin/pricing"


def sign_in(account, password) -> APIClient:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": account.email, "password": password},
                           format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def finance(admin_user):
    """SUPER_ADMIN: manages pricing, may approve a loss."""
    return sign_in(admin_user, "Correct-Horse-Battery-3")


@pytest.fixture
def admin_viewer(db):
    account = User.objects.create_user(email="ops@verifygh.local",
                                       password="Correct-Horse-Battery-5", role=Role.ADMIN,
                                       is_email_verified=True)
    return sign_in(account, "Correct-Horse-Battery-5")


@pytest.fixture
def tiktok_us(catalog):
    """The brief's example, set up exactly."""
    offering = ProviderService.objects.select_related("service", "country", "provider").get(
        service__slug="tiktok", country__code="US")
    ProviderService.objects.filter(pk=offering.pk).update(cost_amount=Decimal("0.50"),
                                                          cost_currency="USD")
    PricingFXRate.objects.create(base_currency="USD", mode="MANUAL", manual_rate=Decimal("15.20"))
    PricingRule.objects.create(
        name="TikTok US", service=offering.service, country=offering.country,
        markup_type=MarkupType.PERCENTAGE, markup_percent=Decimal("25"),
        payment_fee_percent=Decimal("0"), risk_buffer_percent=Decimal("0"),
        rounding=Rounding.NONE, min_price=Decimal("0"), max_price=Decimal("500"),
    )
    from apps.pricing.history import refresh_offering_prices

    # Publish the example's price, as a sync would have.
    refresh_offering_prices(source=PriceChangeSource.PROVIDER_COST)
    offering.refresh_from_db()
    return offering


def reload(offering) -> ProviderService:
    return ProviderService.objects.select_related("service", "country", "provider").get(pk=offering.pk)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def test_the_worked_example(tiktok_us):
    quote = quote_for_offering(tiktok_us)

    assert quote.provider_cost == Decimal("0.5000")
    assert quote.exchange_rate == Decimal("15.20")
    assert quote.fx_mode == "MANUAL"
    assert quote.base_cost == Decimal("7.60")
    assert quote.customer_price == Decimal("9.50")
    assert quote.gross_profit == Decimal("1.90")
    assert quote.markup_percent_effective == Decimal("25.00")
    assert quote.gross_margin_percent == Decimal("20.00")


def test_fixed_markup(tiktok_us):
    PricingRule.objects.filter(name="TikTok US").update(markup_type=MarkupType.FIXED,
                                                         markup_fixed=Decimal("2.00"))
    assert quote_for_offering(tiktok_us).customer_price == Decimal("9.60")


def test_country_markup_beats_global_and_service_markup(tiktok_us, pricing_rule):
    ca = ProviderService.objects.get(service__slug="tiktok", country__code="CA")
    PricingRule.objects.create(
        name="TikTok everywhere", service=tiktok_us.service, markup_percent=Decimal("30"),
        payment_fee_percent=0, risk_buffer_percent=0, rounding=Rounding.NONE, min_price=0)

    assert quote_for_offering(tiktok_us).pricing_rule_name == "TikTok US"
    assert quote_for_offering(ca).pricing_rule_name == "TikTok everywhere"


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------


def test_automatic_fx_is_market_plus_adjustment(catalog):
    ExchangeRate.objects.create(rate=Decimal("14.70"), source="api")
    PricingFXRate.objects.create(base_currency="USD", mode="AUTOMATIC",
                                 adjustment_percent=Decimal("3.40"))

    fx = pricing_fx("USD")

    assert fx.market_rate == Decimal("14.70")
    assert fx.rate == Decimal("15.199800")


def test_a_manual_pricing_rate_does_not_go_stale(catalog):
    ExchangeRate.objects.update(fetched_at=timezone.now() - timedelta(days=30))
    PricingFXRate.objects.create(base_currency="USD", mode="MANUAL", manual_rate=Decimal("15.20"))

    assert pricing_fx("USD").rate == Decimal("15.20")


def test_an_automatic_rate_on_stale_market_data_stops_pricing(catalog):
    from apps.common.errors import ServiceUnavailable

    ExchangeRate.objects.update(fetched_at=timezone.now() - timedelta(days=30))
    PricingFXRate.objects.create(base_currency="USD", mode="AUTOMATIC")

    with pytest.raises(ServiceUnavailable):
        pricing_fx("USD")


def test_changing_the_pricing_fx_is_previewed_then_applied_and_audited(finance, tiktok_us):
    preview = finance.post(f"{P}/fx/preview/", {"currency": "USD", "mode": "MANUAL",
                                                 "manual_rate": "16.00"}, format="json").data
    assert preview["changed"] >= 1
    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("9.50")  # unchanged

    response = finance.put(f"{P}/fx/", {"currency": "USD", "mode": "MANUAL", "manual_rate": "16.00",
                                        "reason": "Cedi weakened this week"}, format="json")

    assert response.status_code == 200, response.data
    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("10.00")
    action = AdminAction.objects.get(action="PRICING_FX_UPDATE")
    assert action.before["manual_rate"] == "15.200000"
    assert action.after["manual_rate"] == "16.00"
    assert PriceChange.objects.filter(source=PriceChangeSource.EXCHANGE_RATE).exists()


# ---------------------------------------------------------------------------
# Overrides, loss and minimum margin
# ---------------------------------------------------------------------------


def test_an_override_replaces_the_price_but_keeps_the_calculated_one_visible(finance, admin_user,
                                                                          tiktok_us):
    response = finance.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                            {"price": "8.99", "reason": "Match a competitor"}, format="json")

    assert response.status_code == 200, response.data
    published = response.data["published"]
    assert published["customer_price"] == "8.99"
    assert published["calculated_price"] == "9.50"
    assert published["override_price"] == "8.99"
    change = PriceChange.objects.get(source=PriceChangeSource.OVERRIDE)
    assert (change.old_price, change.new_price) == (Decimal("9.50"), Decimal("8.99"))
    assert change.changed_by == admin_user and change.reason == "Match a competitor"
    assert AdminAction.objects.filter(action="PRICING_OVERRIDE_SET").exists()

    finance.delete(f"{P}/offerings/{tiktok_us.pk}/override/", {"reason": "Promotion over"},
                   format="json")
    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("9.50")


def test_a_loss_making_override_needs_explicit_approval(finance, admin_viewer, tiktok_us):
    below_cost = {"price": "7.00", "reason": "Launch promotion"}

    refused = finance.post(f"{P}/offerings/{tiktok_us.pk}/override/", below_cost, format="json")
    assert refused.status_code == 409
    assert "below what the number costs" in refused.data["error"]["message"]

    not_allowed = admin_viewer.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                                    {**below_cost, "allow_loss": True}, format="json")
    assert not_allowed.status_code == 403

    approved = finance.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                            {**below_cost, "allow_loss": True}, format="json")
    assert approved.status_code == 200, approved.data
    quote = quote_for_offering(reload(tiktok_us))
    assert quote.customer_price == Decimal("7.00") and quote.is_loss


def test_minimum_margin_warns_by_default_and_blocks_when_enforced(finance, tiktok_us):
    PricingPolicy.objects.update_or_create(pk=1, defaults={"minimum_margin_percent": Decimal("15")})
    preview = finance.post(f"{P}/preview/", {"offering_id": str(tiktok_us.pk),
                                              "override_price": "8.20"}, format="json").data
    assert "BELOW_MINIMUM_MARGIN" in preview["warnings"]  # 0.60 / 8.20 = 7.3%

    ok = finance.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                      {"price": "8.20", "reason": "Allowed with a warning"}, format="json")
    assert ok.status_code == 200

    finance.put(f"{P}/policy/", {"enforce_minimum_margin": True, "reason": "Protect margin"},
                format="json")
    blocked = finance.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                           {"price": "8.10", "reason": "Too thin now"}, format="json")
    assert blocked.status_code == 409
    assert "minimum" in blocked.data["error"]["message"]


def test_the_preview_changes_nothing(finance, tiktok_us):
    response = finance.post(f"{P}/preview/", {"offering_id": str(tiktok_us.pk),
                                               "markup_type": "PERCENTAGE",
                                               "markup_percent": "30"}, format="json")

    assert response.data["quote"]["customer_price"] == "9.88"
    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("9.50")
    assert not AdminAction.objects.exists()


# ---------------------------------------------------------------------------
# Provider costs, history and publishing
# ---------------------------------------------------------------------------


def _provider_raises_cost(offering, new_cost: str):
    """What a sync does when the provider's price list moves."""
    from apps.verification.base import ProviderServiceDTO

    dto = ProviderServiceDTO(code="tiktok", name="TikTok", country_code="US",
                             cost=Decimal(new_cost), currency="USD")
    from apps.verification.mock import MockVerificationProvider

    original = MockVerificationProvider.get_services
    MockVerificationProvider.get_services = lambda self: [dto]
    try:
        sync_catalog("mock")
    finally:
        MockVerificationProvider.get_services = original


def test_a_provider_price_change_is_recorded_and_republished(tiktok_us):
    _provider_raises_cost(tiktok_us, "0.60")

    change = ProviderCostChange.objects.filter(offering=tiktok_us).latest("created_at")
    assert (change.old_cost, change.new_cost) == (Decimal("0.5000"), Decimal("0.6000"))
    assert (change.source, change.sync_method) == ("PROVIDER_API", "CATALOG_SYNC")
    # 0.60 x 15.20 = 9.12; +25% = 11.40
    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("11.40")


def test_with_review_mode_on_a_cost_change_waits_to_be_published(finance, tiktok_us):
    from apps.pricing.history import refresh_offering_prices

    refresh_offering_prices(source=PriceChangeSource.INITIAL)  # publish 9.50
    PricingPolicy.objects.update_or_create(pk=1, defaults={"auto_publish_prices": False})

    _provider_raises_cost(tiktok_us, "0.52")  # 7.904 -> 9.88

    offering = reload(tiktok_us)
    assert offering.price_review_pending is True
    assert offering.recommended_price == Decimal("9.88")
    assert quote_for_offering(offering).customer_price == Decimal("9.50")  # still published

    pending = finance.get(f"{P}/offerings/", {"status": "pending"}).data["results"]
    assert [r["id"] for r in pending] == [str(tiktok_us.pk)]

    finance.post(f"{P}/publish/", {"reason": "Reviewed provider increase"}, format="json")

    assert quote_for_offering(reload(tiktok_us)).customer_price == Decimal("9.88")
    assert PriceChange.objects.filter(source=PriceChangeSource.PUBLISHED).exists()


def test_a_published_price_the_cost_has_overtaken_is_not_sold(tiktok_us):
    from apps.pricing.history import refresh_offering_prices

    refresh_offering_prices(source=PriceChangeSource.INITIAL)
    PricingPolicy.objects.update_or_create(pk=1, defaults={"auto_publish_prices": False})
    _provider_raises_cost(tiktok_us, "0.70")  # cost 10.64 > published 9.50

    with pytest.raises(PriceBelowCost):
        quote_for_offering(reload(tiktok_us))


def test_manual_cost_only_where_the_provider_does_not_supply_one(finance, tiktok_us):
    refused = finance.post(f"{P}/offerings/{tiktok_us.pk}/cost/",
                           {"cost": "0.40", "reason": "Negotiated rate"}, format="json")
    assert refused.status_code == 409

    ProviderService.objects.filter(pk=tiktok_us.pk).update(cost_source="NOT_SYNCED",
                                                          cost_amount=0)
    assert finance.get(f"{P}/offerings/{tiktok_us.pk}/").data["row"]["status"] == "NOT_SYNCED"

    entered = finance.post(f"{P}/offerings/{tiktok_us.pk}/cost/",
                           {"cost": "0.40", "reason": "Quoted by provider by email"}, format="json")
    assert entered.status_code == 200, entered.data
    change = ProviderCostChange.objects.get(source="MANUAL")
    assert change.new_cost == Decimal("0.4000") and change.sync_method == "ADMIN_ENTRY"


def test_an_unknown_cost_is_never_sold(tiktok_us):
    from apps.pricing.engine import CostUnknown

    ProviderService.objects.filter(pk=tiktok_us.pk).update(cost_amount=0)
    with pytest.raises(CostUnknown):
        quote_for_offering(reload(tiktok_us))


# ---------------------------------------------------------------------------
# Orders keep the price they were sold at
# ---------------------------------------------------------------------------


def test_the_order_keeps_its_pricing_snapshot(user, tiktok_us, funded_wallet, finance,
                                              django_capture_on_commit_callbacks):
    funded_wallet(user, "100.00")
    customer = sign_in(user, "Correct-Horse-Battery-1")
    verification_mock.force_scenario("HAPPY")
    with django_capture_on_commit_callbacks(execute=True):
        placed = customer.post("/api/v1/orders/", {"service": "tiktok", "country": "US"},
                               format="json")
    assert placed.data["price"] == "9.50"

    finance.put(f"{P}/fx/", {"currency": "USD", "mode": "MANUAL", "manual_rate": "18.00",
                             "reason": "Big FX move"}, format="json")

    order = Order.objects.get(reference=placed.data["reference"])
    snapshot = order.price_breakdown
    assert order.price == Decimal("9.50")
    assert snapshot["provider_cost"] == "0.5000"
    assert Decimal(snapshot["exchange_rate"]) == Decimal("15.20")
    assert snapshot["base_cost"] == "7.60"
    assert snapshot["gross_profit"] == "1.90"
    assert snapshot["gross_margin_percent"] == "20.00"
    assert Decimal(snapshot["applied"]["markup_percent"]) == Decimal("25")
    assert snapshot["override_price"] is None
    admin_view = finance.get(f"/api/v1/admin/orders/{order.reference}/").data
    assert Decimal(admin_view["price_breakdown"]["exchange_rate"]) == Decimal("15.20")


# ---------------------------------------------------------------------------
# Bulk markup
# ---------------------------------------------------------------------------


def test_bulk_markup_previews_then_applies_on_confirmation(finance, catalog, pricing_rule):
    body = {"scope": {"country": "US"}, "markup_type": "PERCENTAGE", "markup_percent": "30"}

    preview = finance.post(f"{P}/bulk/", body, format="json").data
    assert preview["offerings"] > 0 and preview["governed_by_this_rule"] == preview["offerings"]
    assert not PricingRule.objects.filter(country__code="US").exists()

    no_reason = finance.post(f"{P}/bulk/", {**body, "confirm": True}, format="json")
    assert no_reason.status_code == 400

    applied = finance.post(f"{P}/bulk/", {**body, "confirm": True, "reason": "US price rise"},
                           format="json")
    assert applied.status_code == 200, applied.data
    rule = PricingRule.objects.get(country__code="US", service=None, provider=None)
    assert rule.markup_percent == Decimal("30")
    assert AdminAction.objects.filter(action="PRICING_MARKUP_UPDATE").exists()


# ---------------------------------------------------------------------------
# Visibility and permissions
# ---------------------------------------------------------------------------


def test_the_table_shows_every_step(finance, tiktok_us):
    rows = finance.get(f"{P}/offerings/", {"search": "tiktok", "country": "US"}).data["results"]

    row = rows[0]
    assert row["provider_cost"] == "0.5000" and row["currency"] == "USD"
    assert Decimal(row["fx_rate"]) == Decimal("15.20") and row["ghs_cost"] == "7.60"
    assert row["markup"] == "25%" and row["customer_price"] == "9.50"
    assert row["gross_profit"] == "1.90" and row["gross_margin_percent"] == "20.00"
    assert row["status"] == "ACTIVE"
    assert row["provider"]["demo"] is True  # the mock provider's costs are demo data

    thin = finance.get(f"{P}/offerings/", {"margin_max": "10"}).data["results"]
    assert all(Decimal(r["gross_margin_percent"]) <= 10 for r in thin)


def test_summary_and_audit(finance, tiktok_us):
    finance.post(f"{P}/offerings/{tiktok_us.pk}/override/",
                 {"price": "8.99", "reason": "Match a competitor"}, format="json")

    summary = finance.get(f"{P}/summary/").data
    assert summary["active_overrides"] == 1
    assert Decimal(summary["fx"][0]["pricing_rate"]) == Decimal("15.20")

    audit = finance.get(f"{P}/audit/").data["results"]
    assert audit[0]["action"] == "PRICING_OVERRIDE_SET"
    assert audit[0]["after"]["override"] == "8.99"
    assert audit[0]["after"]["service"] == tiktok_us.service.name


def test_admins_can_see_pricing_but_not_change_it(admin_viewer, tiktok_us):
    assert admin_viewer.get(f"{P}/summary/").status_code == 200
    assert admin_viewer.get(f"{P}/offerings/").status_code == 200

    for method, url, body in [
        ("put", f"{P}/fx/", {"currency": "USD", "mode": "MANUAL", "manual_rate": "1", "reason": "xxxxx"}),
        ("put", f"{P}/policy/", {"auto_publish_prices": False, "reason": "xxxxx"}),
        ("post", f"{P}/offerings/{tiktok_us.pk}/override/", {"price": "9", "reason": "xxxxx"}),
        ("post", f"{P}/publish/", {"reason": "xxxxx"}),
        ("post", f"{P}/bulk/", {"scope": {}, "markup_type": "PERCENTAGE", "markup_percent": "1",
                                "confirm": True, "reason": "xxxxx"}),
    ]:
        assert getattr(admin_viewer, method)(url, body, format="json").status_code == 403, url
    assert not AdminAction.objects.exists()


def test_support_cannot_see_pricing(support_user, tiktok_us):
    support = sign_in(support_user, "Correct-Horse-Battery-4")

    assert support.get(f"{P}/summary/").status_code == 403
    assert support.get(f"{P}/offerings/").status_code == 403
