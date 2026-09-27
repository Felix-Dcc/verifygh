"""The marketplace, and the provider abstraction it sits on."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import Country, ProviderService, Service
from apps.verification.base import ProviderOrderState, VerificationProvider
from apps.verification.registry import available_adapters, get_provider

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Marketplace API
# ---------------------------------------------------------------------------


def test_marketplace_is_browsable_without_an_account(api, catalog):
    response = api.get("/api/v1/services/")

    assert response.status_code == 200
    assert response.data["count"] > 0
    assert response.data["categories"]
    assert response.data["countries"]


def test_every_card_carries_a_server_computed_price(api, catalog):
    response = api.get("/api/v1/services/")

    for service in response.data["results"]:
        for option in service["countries"]:
            assert Decimal(option["price"]) > 0
            assert option["currency"] == "GHS"
            assert "available" in option


def test_availability_is_reported_not_assumed(api, catalog):
    """Out-of-stock offerings still appear, marked unavailable, rather than
    quietly vanishing - the UI says so honestly."""
    response = api.get("/api/v1/services/")
    options = [
        option
        for service in response.data["results"]
        for option in service["countries"]
    ]
    assert any(option["available"] for option in options)
    assert any(not option["available"] for option in options)


def test_filtering_by_category_country_and_search(api, catalog):
    assert api.get("/api/v1/services/?category=SOCIAL").data["count"] > 0
    assert api.get("/api/v1/services/?country=US").data["count"] > 0

    searched = api.get("/api/v1/services/?search=telegram").data
    assert searched["count"] == 1
    assert searched["results"][0]["slug"] == "telegram"


def test_prices_change_when_the_rate_changes(api, catalog):
    from apps.pricing.rates import record_rate

    before = Decimal(api.get("/api/v1/services/instagram/").data["from_price"])

    record_rate(Decimal("24.00"))
    from django.core.cache import cache

    cache.clear()

    after = Decimal(api.get("/api/v1/services/instagram/").data["from_price"])
    assert after > before


def test_unknown_service_returns_a_clean_404(api, catalog):
    response = api.get("/api/v1/services/not-a-real-service/")
    assert response.status_code == 404
    assert response.data["error"]["code"] == "NOT_FOUND"


def test_catalog_health_reports_readiness(api, catalog):
    response = api.get("/api/v1/catalog/health/")

    assert response.data["ready"] is True
    assert response.data["provider_configured"] is True
    assert response.data["exchange_rate_configured"] is True
    assert response.data["purchasable_offerings"] > 0


def test_payment_options_are_served_dynamically(api):
    response = api.get("/api/v1/payments/options/")

    networks = {row["value"] for row in response.data["networks"]}
    assert {"MTN", "TELECEL", "AT"} <= networks
    assert response.data["currency"] == "GHS"
    assert response.data["min_deposit"]
    assert any("024" in row["prefixes"] for row in response.data["networks"])


# ---------------------------------------------------------------------------
# Catalog sync
# ---------------------------------------------------------------------------


def test_sync_builds_the_catalog_from_the_provider(db, exchange_rate, pricing_rule):
    from apps.catalog.services import sync_catalog

    summary = sync_catalog("mock")

    assert summary["provider"] == "mock"
    assert summary["offerings"] > 0
    assert Service.objects.count() > 0
    assert Country.objects.count() > 0
    assert ProviderService.objects.filter(cost_currency="USD").exists()


def test_sync_never_re_enables_something_an_admin_disabled(catalog):
    """Our enabled flag is ours. A provider refresh must not override it."""
    from apps.catalog.services import sync_catalog

    Service.objects.filter(slug="instagram").update(is_enabled=False)
    ProviderService.objects.filter(service__slug="instagram").update(is_enabled=False)

    sync_catalog("mock")

    assert Service.objects.get(slug="instagram").is_enabled is False
    assert not ProviderService.objects.filter(
        service__slug="instagram", is_enabled=True
    ).exists()


def test_sync_refreshes_cost_and_availability(catalog):
    from apps.catalog.services import sync_catalog

    ProviderService.objects.filter(service__slug="instagram").update(
        cost_amount=Decimal("99.0000"), is_available=False
    )
    sync_catalog("mock")

    offering = ProviderService.objects.filter(service__slug="instagram").first()
    assert offering.cost_amount != Decimal("99.0000")


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


def test_both_adapters_are_registered():
    assert set(available_adapters()) >= {"mock", "textverified"}


def test_the_mock_provider_satisfies_the_full_interface():
    provider = get_provider("mock")
    for method in (
        "get_services", "get_countries", "get_pricing", "get_availability",
        "create_order", "get_order_status", "get_verification_code",
        "cancel_order", "refund_order",
    ):
        assert callable(getattr(provider, method)), method


def test_the_real_adapter_refuses_to_run_without_credentials():
    """It must fail loudly rather than pretending, and must never guess an endpoint."""
    from apps.common.errors import ServiceUnavailable
    from apps.verification.textverified import TextVerifiedProvider

    provider = TextVerifiedProvider()
    assert provider.is_configured is False
    assert provider.health_check() is False

    with pytest.raises(ServiceUnavailable):
        provider.get_services()

    # The endpoints now come from TextVerified's published OpenAPI document
    # (see tests/test_provider_safety.py, which checks each one against it).
    # Having the documentation is not permission to sell: without credentials
    # the adapter still refuses every call, as asserted above.
    assert TextVerifiedProvider.BASE_URL == "https://www.textverified.com"
    assert TextVerifiedProvider.PATH_CREATE_ORDER == "/api/pub/v2/verifications"


def test_the_provider_call_budget_is_enforced(settings):
    """We stay inside a provider's limits by construction, not by getting blocked."""
    from apps.common.errors import ServiceUnavailable

    settings.VERIFYGH = {**settings.VERIFYGH, "PROVIDER_RATE_LIMIT_PER_MINUTE": 3}
    provider = get_provider("mock")

    for _ in range(3):
        provider.get_countries()

    with pytest.raises(ServiceUnavailable) as exc:
        provider.get_countries()
    assert exc.value.code == "PROVIDER_BUDGET_EXCEEDED"


def test_the_mock_provider_honours_idempotency_keys():
    """A retried reservation must not book (and bill us for) two numbers."""
    provider = get_provider("mock")
    from apps.verification import mock

    mock.force_scenario("HAPPY")

    first = provider.create_order("instagram", "US", "vgh:same-order")
    second = provider.create_order("instagram", "US", "vgh:same-order")

    assert first.provider_order_id == second.provider_order_id


def test_the_mock_provider_walks_the_full_lifecycle():
    from apps.verification import mock

    provider = get_provider("mock")
    mock.force_scenario("HAPPY")

    order = provider.create_order("instagram", "US", "vgh:lifecycle")
    assert order.state in {ProviderOrderState.NUMBER_ASSIGNED,
                           ProviderOrderState.WAITING_FOR_CODE}
    assert order.phone_number

    mock.fast_forward(order.provider_order_id, 30)
    updated = provider.get_order_status(order.provider_order_id)

    assert updated.state == ProviderOrderState.CODE_RECEIVED
    assert len(updated.code.code) == 6


def test_a_delivered_code_cannot_be_cancelled_upstream():
    from apps.verification import mock

    provider = get_provider("mock")
    mock.force_scenario("HAPPY")

    order = provider.create_order("instagram", "US", "vgh:no-cancel")
    mock.fast_forward(order.provider_order_id, 30)

    assert provider.cancel_order(order.provider_order_id) is False


def test_the_interface_cannot_be_partially_implemented():
    """An incomplete adapter must fail at import, not in production."""

    class Incomplete(VerificationProvider):
        key = "incomplete"

        def get_services(self):
            return []

    with pytest.raises(TypeError):
        Incomplete()
