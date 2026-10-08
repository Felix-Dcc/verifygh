"""Live stock follows the provider, and never charges for what it cannot supply.

8 Oct 2026: WhatsApp purchases were charged and then refunded because
TextVerified refused them as "Out of stock or unavailable" seconds after its
inventory endpoint reported stock. See apps/catalog/stock.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.catalog import stock
from apps.catalog.models import ProviderService
from apps.catalog.services import sync_catalog
from apps.common.errors import ProviderError
from apps.orders.models import Order
from apps.verification import mock as verification_mock
from apps.verification.base import AvailabilityDTO
from apps.verification.mock import MockVerificationProvider
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

MARKET = "/api/v1/marketplace/"


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def calls(monkeypatch):
    """Count stock calls and set what the provider answers."""
    state = {"n": 0, "answer": AvailabilityDTO(available=True, count=50), "fail": False}

    def fake(self, service, country):
        state["n"] += 1
        if state["fail"]:
            raise ProviderError("timeout")
        return state["answer"]

    monkeypatch.setattr(MockVerificationProvider, "get_availability", fake)
    return state


def offering(slug="tiktok", country="US") -> ProviderService:
    return ProviderService.objects.select_related("provider", "service", "country").get(
        service__slug=slug, country__code=country)


def buy(client, slug="tiktok"):
    return client.post("/api/v1/orders/", {"service": slug, "country": "US"}, format="json")


def us_option(api, slug="tiktok"):
    return next(c for c in api.get(f"{MARKET}{slug}/").data["countries"] if c["code"] == "US")


# -- display ------------------------------------------------------------------


def test_the_purchase_screen_shows_out_of_stock(api, catalog, calls):
    calls["answer"] = AvailabilityDTO(available=False, count=0)
    option = us_option(api)
    assert option["availability"] == "UNAVAILABLE" and option["stock_error"] is False


def test_stock_returning_shows_as_available_again(api, catalog, calls):
    calls["answer"] = AvailabilityDTO(available=False, count=0)
    assert us_option(api)["availability"] == "UNAVAILABLE"
    calls["answer"] = AvailabilityDTO(available=True, count=40)
    stock.recheck_out_of_stock()
    assert us_option(api)["availability"] != "UNAVAILABLE"


def test_display_checks_are_cached(api, catalog, calls):
    us_option(api)
    us_option(api)
    us_option(api)
    assert calls["n"] == 1


def test_a_provider_error_is_not_out_of_stock(api, catalog, calls):
    calls["fail"] = True
    option = us_option(api)
    assert option["stock_error"] is True
    assert option["availability"] != "UNAVAILABLE"      # what we last knew stands
    assert offering().is_available is True


# -- purchase -----------------------------------------------------------------


def test_the_final_check_is_always_fresh(user, auth, catalog, funded_wallet, calls,
                                         api):
    funded_wallet(user, "100.00")
    us_option(api)                                       # cached: in stock
    calls["answer"] = AvailabilityDTO(available=False, count=0)
    response = buy(auth(user))
    assert response.status_code == 503 and response.data["error"]["code"] == "NO_AVAILABILITY"
    assert not Order.objects.exists()
    assert get_or_create_wallet(user).balance == Decimal("100.00")


def test_a_failed_stock_check_refuses_without_charging(user, auth, catalog, funded_wallet,
                                                       calls):
    funded_wallet(user, "100.00")
    calls["fail"] = True
    response = buy(auth(user))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert not Order.objects.exists()
    assert get_or_create_wallet(user).balance == Decimal("100.00")


def test_a_refused_purchase_holds_the_service_out_of_stock(
        user, auth, catalog, funded_wallet, calls, api, monkeypatch,
        django_capture_on_commit_callbacks):
    """The inventory says yes, the purchase says no: the refusal wins."""
    funded_wallet(user, "100.00")

    def refuse(self, *args, **kwargs):
        error = ProviderError("Out of stock or unavailable.")
        error.provider_code = "Unavailable"
        raise error

    monkeypatch.setattr(MockVerificationProvider, "create_order", refuse)
    client = auth(user)
    with django_capture_on_commit_callbacks(execute=True):
        first = buy(client)
    assert first.status_code == 201
    assert get_or_create_wallet(user).balance == Decimal("100.00")   # refunded

    # The inventory still says yes - it is not believed during the hold.
    assert calls["answer"].available is True
    assert us_option(api)["availability"] == "UNAVAILABLE"
    second = buy(client)
    assert second.status_code == 503 and second.data["error"]["code"] == "NO_AVAILABILITY"
    assert Order.objects.count() == 1                    # no second charge

    # Rechecks wait out the hold...
    stock.recheck_out_of_stock()
    assert offering().is_available is False
    # ...then trust the provider again, so returning stock shows.
    cache.delete(f"stock:hold:{offering().pk}")
    stock.recheck_out_of_stock()
    assert offering().is_available is True


def test_repeat_refusals_hold_longer(catalog, monkeypatch):
    held = []
    real_set = stock._cache_set
    monkeypatch.setattr(stock, "_cache_set", lambda key, value, seconds: (
        held.append(seconds) if key.startswith("stock:hold:") else None,
        real_set(key, value, seconds)))
    for _ in range(4):
        stock.note_refused(offering())
    assert held == [600, 1200, 2400, 3600]


def test_the_catalogue_sync_does_not_overwrite_stock(catalog, monkeypatch):
    """TextVerified's service list has no stock; a sync must not mark it in stock."""
    from apps.verification.base import ProviderServiceDTO

    stock.note_refused(offering())
    real = MockVerificationProvider.get_services

    def priced_only(self, *args, **kwargs):
        return [ProviderServiceDTO(**{**dto.__dict__, "reports_stock": False})
                for dto in real(self, *args, **kwargs)]

    monkeypatch.setattr(MockVerificationProvider, "get_services", priced_only)
    sync_catalog("mock")
    assert offering().is_available is False


def test_happy_path_still_buys(user, auth, catalog, funded_wallet, calls,
                               django_capture_on_commit_callbacks):
    funded_wallet(user, "100.00")
    verification_mock.force_scenario("HAPPY")
    with django_capture_on_commit_callbacks(execute=True):
        response = buy(auth(user))
    assert response.status_code == 201
    assert get_or_create_wallet(user).balance < Decimal("100.00")


# -- call budget --------------------------------------------------------------


def _out_of_stock(*slugs):
    ProviderService.objects.filter(service__slug__in=slugs, country__code="US").update(
        is_available=False, available_count=0)


def test_concurrent_visitors_share_one_check(api, catalog, calls):
    cache.set(f"stock:inflight:{offering().pk}", 1, 10)   # someone is asking now
    us_option(api)
    assert calls["n"] == 0


def test_a_recheck_backs_off_while_still_out_of_stock(catalog, calls):
    _out_of_stock("tiktok")
    calls["answer"] = AvailabilityDTO(available=False, count=0)
    first = stock.recheck_out_of_stock()["asked"]
    assert first >= 1
    assert stock.recheck_out_of_stock()["asked"] == 0      # not due for 2 minutes
    assert calls["n"] == first


def test_only_one_recheck_runs_at_a_time(catalog, calls):
    _out_of_stock("tiktok")
    cache.set("stock:recheck:lock", 1, 60)
    assert stock.recheck_out_of_stock()["skipped"] == "running"
    assert calls["n"] == 0


def test_a_recheck_stops_at_the_first_provider_error(catalog, calls):
    slugs = list(ProviderService.objects.filter(country__code="US")
                 .values_list("service__slug", flat=True)[:3])
    _out_of_stock(*slugs)
    calls["fail"] = True
    assert stock.recheck_out_of_stock()["asked"] == 1
    assert calls["n"] == 1


def test_background_work_stands_aside_after_a_429():
    import time

    from apps.verification import pacing

    pacing.note_throttled("textverified")
    assert pacing.throttled("textverified")
    assert pacing.wait_turn("textverified", time.monotonic() + 0.5) is False
    assert pacing.interval("textverified") >= pacing.START_INTERVAL * 2


def test_the_sync_skips_prices_it_fetched_recently(catalog, monkeypatch):
    seen = {}
    real = MockVerificationProvider.get_services

    def spy(self, *args, skip=None, **kwargs):
        seen["skip"] = skip
        return real(self, *args, skip=skip, **kwargs)

    monkeypatch.setattr(MockVerificationProvider, "get_services", spy)
    sync_catalog("mock")
    assert "tiktok" in seen["skip"]


def test_a_sync_that_changes_nothing_reprices_nothing(catalog, monkeypatch):
    repriced = []
    monkeypatch.setattr("apps.pricing.history.refresh_offering_prices",
                        lambda **kwargs: repriced.append(kwargs) or {"changed": 0})
    summary = sync_catalog("mock")
    assert repriced == [] and summary["price_changes"] == 0
