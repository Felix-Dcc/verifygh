"""The SMS Verifications marketplace: countries, search, pins, popularity,
availability, and the pricing engine and price history behind it."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.catalog.models import PinnedService, ProviderService, Service
from apps.common.errors import ProviderError
from apps.orders.models import Order
from apps.pricing.engine import PriceBelowCost, quote_for_offering
from apps.pricing.models import MarkupType, PriceChange, PriceChangeSource, PricingRule, Rounding
from apps.verification import mock as verification_mock
from apps.verification.base import AvailabilityDTO
from apps.verification.mock import MockVerificationProvider
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

MARKET = "/api/v1/marketplace/"


def sign_in(account: User, password: str) -> APIClient:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": account.email, "password": password},
                           format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def customer(user):
    return sign_in(user, "Correct-Horse-Battery-1")


def slugs(rows) -> list[str]:
    return [row["slug"] for row in rows]


# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------


def test_only_the_united_states_and_canada_are_offered(api, catalog):
    home = api.get(f"{MARKET}home/").data

    assert [c["code"] for c in home["countries"]] == ["US", "CA"]
    assert home["country"] == "US"
    assert [c["code"] for c in api.get("/api/v1/countries/").data] == ["US", "CA"]
    # The mock provider also sells GB, NL and DE; none of it leaks through.
    legacy = api.get("/api/v1/services/", {"country": "GB"}).data
    assert legacy["results"] == []


@pytest.mark.parametrize("country", ["GB", "NL", "de", "GH", "ZZ"])
def test_other_countries_are_refused_everywhere(api, catalog, customer, user, funded_wallet,
                                                country):
    funded_wallet(user, "100.00")

    assert api.get(MARKET, {"country": country}).status_code == 400
    assert customer.get("/api/v1/orders/quote/",
                        {"service": "instagram", "country": country}).status_code == 400
    response = customer.post("/api/v1/orders/", {"service": "instagram", "country": country},
                             format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "UNSUPPORTED_COUNTRY"
    assert not Order.objects.exists()
    assert get_or_create_wallet(user).balance == Decimal("100.00")


def test_us_and_canada_each_list_their_own_availability(api, catalog):
    us = api.get(MARKET, {"country": "US", "include_unavailable": "true"}).data["results"]
    ca = api.get(MARKET, {"country": "CA", "include_unavailable": "true"}).data["results"]

    us_amazon = next(row for row in us if row["slug"] == "amazon")
    ca_amazon = next(row for row in ca if row["slug"] == "amazon")
    assert us_amazon["availability"] == "UNAVAILABLE"
    assert ca_amazon["availability"] in {"AVAILABLE", "LIMITED"}
    # The default list shows only what can be bought.
    assert "amazon" not in slugs(api.get(MARKET, {"country": "US"}).data["results"])
    assert "amazon" in slugs(api.get(MARKET, {"country": "CA"}).data["results"])


def test_the_same_service_can_cost_differently_per_country(api, catalog):
    us = {r["slug"]: r for r in api.get(MARKET, {"country": "US"}).data["results"]}
    ca = {r["slug"]: r for r in api.get(MARKET, {"country": "CA"}).data["results"]}

    assert us["tiktok"]["price"] != ca["tiktok"]["price"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_is_case_insensitive_and_server_side(api, catalog):
    for query in ("TIKTOK", "tiktok", "TikT", "  tik  "):
        assert slugs(api.get(MARKET, {"search": query}).data["results"])[0] == "tiktok", query


def test_search_finds_services_by_what_people_call_them(api, catalog):
    Service.objects.filter(slug="google").update(aliases="gmail, youtube")
    from apps.catalog.marketplace import invalidate

    invalidate()

    assert slugs(api.get(MARKET, {"search": "gmail"}).data["results"]) == ["google"]
    # An exact name beats names that merely contain the letter.
    assert slugs(api.get(MARKET, {"search": "x"}).data["results"])[0] == "x"


def test_search_with_no_match_is_empty_not_an_error(api, catalog):
    response = api.get(MARKET, {"search": "no-such-service-anywhere"})

    assert response.status_code == 200
    assert response.data["results"] == []


def test_the_list_is_paginated(api, catalog):
    first = api.get(MARKET, {"page_size": 5}).data
    second = api.get(MARKET, {"page_size": 5, "page": 2}).data

    assert len(first["results"]) == 5 and first["has_next"] is True
    assert set(slugs(first["results"])).isdisjoint(slugs(second["results"]))


# ---------------------------------------------------------------------------
# Availability: only what the provider said
# ---------------------------------------------------------------------------


def _set_count(slug, country, count, available=True):
    ProviderService.objects.filter(service__slug=slug, country__code=country).update(
        available_count=count, is_available=available
    )
    from apps.catalog.marketplace import invalidate

    invalidate()


def _row(api, slug, country="US"):
    rows = api.get(MARKET, {"country": country, "include_unavailable": "true"}).data["results"]
    return next(row for row in rows if row["slug"] == slug)


def test_a_reported_count_is_shown(api, catalog):
    _set_count("tiktok", "US", 120)
    row = _row(api, "tiktok")
    assert row["availability"] == "AVAILABLE" and row["available_count"] == 120


def test_a_ceiling_like_count_is_not_presented_as_stock(api, catalog):
    _set_count("tiktok", "US", 9999)
    row = _row(api, "tiktok")

    assert row["availability"] == "AVAILABLE"
    assert row["available_count"] is None


def test_no_count_means_available_without_a_number(api, catalog):
    _set_count("tiktok", "US", None)
    row = _row(api, "tiktok")

    assert row["availability"] == "AVAILABLE" and row["available_count"] is None


def test_low_stock_is_limited_and_none_is_unavailable(api, catalog):
    _set_count("tiktok", "US", 3)
    assert _row(api, "tiktok")["availability"] == "LIMITED"

    _set_count("tiktok", "US", 0)
    assert _row(api, "tiktok")["availability"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Popular
# ---------------------------------------------------------------------------


def test_known_services_arrive_as_staff_picks(api, catalog):
    """The presentation table marks TikTok, WhatsApp and friends as picks."""
    popular = slugs(api.get(f"{MARKET}home/").data["popular"])

    assert popular[:3] == ["tiktok", "whatsapp", "telegram"]
    assert Service.objects.get(slug="google").name == "Google / Gmail"


def test_popular_starts_with_staff_picks_in_their_order(api, catalog):
    Service.objects.update(is_popular=False)
    Service.objects.filter(slug="telegram").update(is_popular=True, popular_rank=1)
    Service.objects.filter(slug="tiktok").update(is_popular=True, popular_rank=2)

    popular = slugs(api.get(f"{MARKET}home/").data["popular"])

    assert popular[:2] == ["telegram", "tiktok"]


def test_popular_never_shows_what_cannot_be_bought_here(api, catalog):
    Service.objects.filter(slug="amazon").update(is_popular=True, popular_rank=1)

    assert "amazon" not in slugs(api.get(f"{MARKET}home/", {"country": "US"}).data["popular"])
    assert "amazon" in slugs(api.get(f"{MARKET}home/", {"country": "CA"}).data["popular"])


def test_with_no_picks_and_no_orders_nothing_is_called_popular(api, catalog):
    Service.objects.update(is_popular=False)
    assert api.get(f"{MARKET}home/").data["popular"] == []


def test_real_activity_makes_a_service_popular(user, customer, catalog, funded_wallet):
    Service.objects.update(is_popular=False)
    funded_wallet(user, "200.00")
    verification_mock.force_scenario("HAPPY")
    customer.post("/api/v1/orders/", {"service": "discord", "country": "US"}, format="json")

    assert slugs(customer.get(f"{MARKET}home/").data["popular"]) == ["discord"]


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------


def test_pins_follow_the_customer_to_another_device(user, customer, catalog):
    assert customer.post(f"{MARKET}tiktok/pin/").status_code == 200
    assert customer.post(f"{MARKET}whatsapp/pin/").status_code == 200

    other_device = sign_in(user, "Correct-Horse-Battery-1")
    home = other_device.get(f"{MARKET}home/").data

    assert slugs(home["pinned"]) == ["tiktok", "whatsapp"]
    listed = {r["slug"]: r["pinned"] for r in other_device.get(MARKET).data["results"]}
    assert listed["tiktok"] is True and listed["telegram"] is False


def test_pinning_twice_pins_once_and_unpinning_removes_it(user, customer, catalog):
    customer.post(f"{MARKET}tiktok/pin/")
    customer.post(f"{MARKET}tiktok/pin/")
    assert PinnedService.objects.filter(user=user).count() == 1

    response = customer.delete(f"{MARKET}tiktok/pin/")

    assert response.data["pinned"] == []
    assert not PinnedService.objects.exists()


def test_pins_are_private_to_each_customer(user, other_user, customer, catalog):
    customer.post(f"{MARKET}tiktok/pin/")
    stranger = sign_in(other_user, "Correct-Horse-Battery-2")

    assert stranger.get(f"{MARKET}home/").data["pinned"] == []


def test_pinning_needs_an_account(api, catalog):
    assert api.post(f"{MARKET}tiktok/pin/").status_code in (401, 403)
    assert api.get(f"{MARKET}home/").data["pinned"] == []


def test_a_pinned_service_out_of_stock_stays_visible(user, customer, catalog):
    customer.post(f"{MARKET}amazon/pin/")

    pinned = customer.get(f"{MARKET}home/", {"country": "US"}).data["pinned"]

    assert pinned[0]["slug"] == "amazon"
    assert pinned[0]["availability"] == "UNAVAILABLE"


def test_an_unknown_service_cannot_be_pinned(customer, catalog):
    assert customer.post(f"{MARKET}no-such-service/pin/").status_code == 404


# ---------------------------------------------------------------------------
# Purchase protection
# ---------------------------------------------------------------------------


def test_the_purchase_screen_prices_both_countries(api, catalog):
    detail = api.get(f"{MARKET}tiktok/").data

    assert [c["code"] for c in detail["countries"]] == ["US", "CA"]
    assert all(c["offered"] and Decimal(c["price"]) > 0 for c in detail["countries"])


def test_live_stock_is_checked_before_charging(user, customer, catalog, funded_wallet,
                                               monkeypatch):
    funded_wallet(user, "100.00")
    monkeypatch.setattr(MockVerificationProvider, "get_availability",
                        lambda self, s, c: AvailabilityDTO(available=False, count=0))

    response = customer.post("/api/v1/orders/", {"service": "tiktok", "country": "US"},
                             format="json")

    assert response.status_code == 503
    assert response.data["error"]["code"] == "NO_AVAILABILITY"
    assert not Order.objects.exists()
    assert get_or_create_wallet(user).balance == Decimal("100.00")
    # The catalogue learns from the live answer.
    assert ProviderService.objects.get(service__slug="tiktok",
                                       country__code="US").is_available is False


def test_an_unreachable_provider_charges_nothing(user, customer, catalog, funded_wallet,
                                                 monkeypatch):
    funded_wallet(user, "100.00")

    def boom(self, service, country):
        raise ProviderError("timeout")

    monkeypatch.setattr(MockVerificationProvider, "get_availability", boom)

    response = customer.post("/api/v1/orders/", {"service": "tiktok", "country": "US"},
                             format="json")

    assert response.status_code == 503
    assert response.data["error"]["code"] == "PROVIDER_UNAVAILABLE"
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("100.00")
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_the_client_cannot_set_the_price(user, customer, catalog, funded_wallet,
                                         django_capture_on_commit_callbacks):
    funded_wallet(user, "100.00")
    verification_mock.force_scenario("HAPPY")
    expected = customer.get("/api/v1/orders/quote/",
                            {"service": "tiktok", "country": "US"}).data["price"]

    with django_capture_on_commit_callbacks(execute=True):
        response = customer.post("/api/v1/orders/", {
            "service": "tiktok", "country": "US", "price": "0.01", "provider": "evil",
            "provider_cost": "0", "available": True,
        }, format="json")

    assert response.status_code == 201
    assert response.data["price"] == expected
    assert get_or_create_wallet(user).balance == Decimal("100.00") - Decimal(expected)


def test_customers_are_not_shown_what_we_pay(user, customer, catalog, funded_wallet,
                                             django_capture_on_commit_callbacks):
    funded_wallet(user, "100.00")
    verification_mock.force_scenario("HAPPY")
    with django_capture_on_commit_callbacks(execute=True):
        order = customer.post("/api/v1/orders/", {"service": "tiktok", "country": "US"},
                              format="json").data

    detail = customer.get(f"/api/v1/orders/{order['reference']}/").data
    for field in ("provider_cost", "provider_currency", "exchange_rate"):
        assert field not in detail
    assert "cost" not in str(customer.get(MARKET).data).lower()


# ---------------------------------------------------------------------------
# Pricing engine
# ---------------------------------------------------------------------------


def _offering(slug="tiktok", country="US") -> ProviderService:
    return ProviderService.objects.select_related("service", "country", "provider").get(
        service__slug=slug, country__code=country
    )


def _rule(**fields) -> PricingRule:
    defaults = dict(name="t", markup_type=MarkupType.PERCENTAGE, markup_percent=Decimal("0"),
                    markup_fixed=Decimal("0"), payment_fee_percent=Decimal("0"),
                    risk_buffer_percent=Decimal("0"), rounding=Rounding.NONE,
                    min_price=Decimal("0.00"), max_price=Decimal("500.00"))
    defaults.update(fields)
    return PricingRule(**defaults)


def test_percentage_margin(catalog):
    offering = _offering()
    base = (offering.cost_amount * Decimal("12.00")).quantize(Decimal("0.01"))

    quote = quote_for_offering(offering, rule=_rule(markup_percent=Decimal("20")))

    assert quote.base_cost == base
    assert quote.customer_price == (base * Decimal("1.20")).quantize(Decimal("0.01"))


def test_fixed_margin(catalog):
    offering = _offering()
    quote = quote_for_offering(offering, rule=_rule(markup_type=MarkupType.FIXED,
                                                    markup_fixed=Decimal("1.50")))

    assert quote.customer_price == quote.base_cost + Decimal("1.50")


def test_the_price_never_falls_below_cost(catalog):
    offering = _offering()
    # A negative fixed margin would sell at a loss.
    quote = quote_for_offering(offering, rule=_rule(markup_type=MarkupType.FIXED,
                                                    markup_fixed=Decimal("-5.00")))

    assert quote.customer_price >= quote.base_cost


def test_the_floor_covers_the_collection_fee_too(catalog):
    offering = _offering()
    rule = _rule(markup_type=MarkupType.FIXED, markup_fixed=Decimal("-5.00"),
                 payment_fee_percent=Decimal("1.95"))

    quote = quote_for_offering(offering, rule=rule)

    assert quote.customer_price >= (quote.base_cost * Decimal("1.0195")).quantize(Decimal("0.01"))


def test_a_ceiling_below_cost_means_not_sold(catalog):
    with pytest.raises(PriceBelowCost):
        quote_for_offering(_offering(), rule=_rule(max_price=Decimal("0.10")))


def test_selling_below_cost_needs_an_explicit_override(catalog):
    quote = quote_for_offering(_offering(), rule=_rule(max_price=Decimal("0.10"),
                                                       allow_below_cost=True))

    assert quote.customer_price == Decimal("0.10")


def test_a_rule_can_target_one_service_in_one_country(api, catalog, pricing_rule):
    offering = _offering()
    PricingRule.objects.create(
        name="TikTok US", service=offering.service, country=offering.country,
        markup_type=MarkupType.FIXED, markup_fixed=Decimal("1.00"),
        payment_fee_percent=Decimal("0"), risk_buffer_percent=Decimal("0"),
        rounding=Rounding.NONE, min_price=Decimal("0"), max_price=Decimal("500"),
    )

    us = quote_for_offering(offering)
    ca = quote_for_offering(_offering(country="CA"))

    assert us.pricing_rule_name == "TikTok US"
    assert ca.pricing_rule_name == pricing_rule.name


def test_a_provider_scoped_rule_beats_a_general_one(catalog, pricing_rule):
    offering = _offering()
    PricingRule.objects.create(
        name="Mock provider", provider=offering.provider,
        markup_type=MarkupType.PERCENTAGE, markup_percent=Decimal("5"),
        payment_fee_percent=Decimal("0"), risk_buffer_percent=Decimal("0"),
        rounding=Rounding.NONE, min_price=Decimal("0"), max_price=Decimal("500"),
    )

    assert quote_for_offering(offering).pricing_rule_name == "Mock provider"


# ---------------------------------------------------------------------------
# Price history and admin pricing
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(admin_user):
    return sign_in(admin_user, "Correct-Horse-Battery-3")


def test_the_first_sync_records_starting_prices(catalog):
    assert PriceChange.objects.filter(source=PriceChangeSource.INITIAL).exists()
    assert not PriceChange.objects.exclude(country_code__in=["US", "CA"]).exists()


def test_a_rule_change_is_recorded_with_who_and_why(super_admin, admin_user, catalog,
                                                    pricing_rule,
                                                    django_capture_on_commit_callbacks):
    before = _offering().customer_price

    with django_capture_on_commit_callbacks(execute=True):
        response = super_admin.patch(f"/api/v1/admin/pricing-rules/{pricing_rule.pk}/",
                                     {"markup_percent": "35.00",
                                      "reason": "Match competitor pricing"}, format="json")

    assert response.status_code == 200, response.data
    change = PriceChange.objects.filter(source=PriceChangeSource.PRICING_RULE,
                                        service_name=_offering().service.name,
                                        country_code="US").get()
    assert change.old_price == before
    assert change.new_price == _offering().customer_price != before
    assert change.changed_by == admin_user
    assert change.reason == "Match competitor pricing"

    listing = super_admin.get("/api/v1/admin/price-changes/", {"source": "PRICING_RULE"}).data
    assert listing["results"][0]["changed_by_email"] == admin_user.email


def test_a_rule_change_without_a_reason_is_refused(super_admin, catalog, pricing_rule):
    response = super_admin.patch(f"/api/v1/admin/pricing-rules/{pricing_rule.pk}/",
                                 {"markup_percent": "35.00"}, format="json")

    assert response.status_code == 400
    pricing_rule.refresh_from_db()
    assert pricing_rule.markup_percent == Decimal("20.00")


def test_a_new_exchange_rate_is_recorded(super_admin, catalog,
                                         django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        super_admin.post("/api/v1/admin/exchange-rates/",
                         {"rate": "13.00", "note": "Weekly update", "reason": "Weekly update"},
                         format="json")

    assert PriceChange.objects.filter(source=PriceChangeSource.EXCHANGE_RATE).exists()


def test_only_finance_staff_can_change_pricing(catalog, pricing_rule, support_user):
    support = sign_in(support_user, "Correct-Horse-Battery-4")
    admin = User.objects.create_user(email="ops@verifygh.local",
                                     password="Correct-Horse-Battery-5", role=Role.ADMIN,
                                     is_email_verified=True)
    ops = sign_in(admin, "Correct-Horse-Battery-5")

    for client in (support, ops):
        response = client.patch(f"/api/v1/admin/pricing-rules/{pricing_rule.pk}/",
                                {"markup_percent": "1.00", "reason": "Trying my luck"},
                                format="json")
        assert response.status_code == 403
    pricing_rule.refresh_from_db()
    assert pricing_rule.markup_percent == Decimal("20.00")


def test_admin_sees_cost_price_and_margin(super_admin, catalog):
    rows = super_admin.get("/api/v1/admin/offerings/",
                           {"marketplace": "1", "search": "tiktok"}).data["results"]

    assert {row["country_code"] for row in rows} == {"US", "CA"}
    row = rows[0]
    assert Decimal(row["customer_price"]) - Decimal(row["base_cost"]) == Decimal(row["margin"])
    assert Decimal(row["customer_price"]) >= Decimal(row["cost_floor"])
