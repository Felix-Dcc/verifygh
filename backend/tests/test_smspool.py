"""SMSPool adapter, against a fake that answers like the published collection's
sample responses (documenter.getpostman.com/view/30155063/2s9YXmZ1JY)."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.catalog.models import Service
from apps.common.errors import ProviderError
from apps.verification.base import ProviderOrderState
from apps.verification.registry import available_adapters
from apps.verification.smspool import SMSPoolProvider, slug_for

pytestmark = pytest.mark.django_db

KEY = "ci-smspool-key-not-real"


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSMSPool:
    def __init__(self):
        self.calls: list[dict] = []
        self.purchase = {"success": 1, "number": 12025550123, "cc": "1",
                         "phonenumber": "2025550123", "order_id": "ABCDEFGH",
                         "expires_in": 1200, "expiration": int(time.time()) + 1200,
                         "cost": "0.60"}
        self.check = {"status": 1, "expiration": int(time.time()) + 1000}

    def __call__(self, method, url, data=None, params=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": dict(data or {}),
                           "params": params})
        path = url.split("api.smspool.net", 1)[1]
        if path == "/country/retrieve_all":
            return _Response([{"ID": 1, "name": "United States", "short_name": "US"},
                              {"ID": 2, "name": "United Kingdom", "short_name": "GB"}])
        if path == "/service/retrieve_all":
            return _Response([{"ID": 907, "name": "Telegram"}, {"ID": 924, "name": "TikTok/Douyin"},
                              {"ID": 1553, "name": "Vercel"}])
        if path == "/request/pricing":
            return _Response([{"service": 907, "pool": 7, "price": "0.60"},
                              {"service": 907, "pool": 12, "price": "1.33"},
                              {"service": 924, "pool": 7, "price": "0.14"},
                              {"service": 1553, "pool": 7, "price": "0.04"}])
        if path == "/request/price":
            return _Response({"pool": 7, "price": "0.60", "high_price": "1.33",
                              "success_rate": 80})
        if path == "/sms/stock":
            return _Response({"success": 1, "amount": 42})
        if path == "/purchase/sms":
            return _Response(self.purchase, 200 if self.purchase.get("success") else 422)
        if path == "/sms/check":
            return _Response(self.check)
        if path == "/sms/cancel":
            return _Response({"success": 1, "message": "cancelled"})
        if path == "/request/balance":
            return _Response({"balance": "5.00"})
        raise AssertionError(path)


@pytest.fixture
def pool(settings, monkeypatch):
    cache.clear()
    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "smspool": {"api_key": KEY, "base_url": ""}}
    settings.VERIFYGH = {**settings.VERIFYGH, "MARKETPLACE_COUNTRIES": ["US"]}
    fake = FakeSMSPool()
    monkeypatch.setattr("apps.verification.smspool.requests.Session.request", fake)
    yield fake
    cache.clear()


def test_it_is_registered():
    assert "smspool" in available_adapters()


@pytest.mark.parametrize("name,slug", [("Twitter / X", "twitter"), ("TikTok/Douyin", "tiktok"),
                                       ("Plenty Of Fish", "plentyoffish"), ("WhatsApp", "whatsapp"),
                                       ("Google/Gmail", "google")])
def test_names_become_our_slugs(name, slug):
    assert slug_for(name) == slug


def test_the_catalogue_is_the_cheapest_price_for_services_we_already_list(pool):
    Service.objects.create(slug="telegram", name="Telegram")
    Service.objects.create(slug="tiktok", name="TikTok")
    offerings = {o.code: o for o in SMSPoolProvider().get_services()}
    assert set(offerings) == {"telegram", "tiktok"}          # Vercel is not in our shop
    assert offerings["telegram"].cost == Decimal("0.60")
    assert offerings["telegram"].country_code == "US"
    assert offerings["telegram"].reports_stock is False


def test_an_order_never_pays_above_the_listed_price_and_keeps_the_key_out_of_urls(pool):
    order = SMSPoolProvider().create_order("telegram", "US", "idem-1")
    buy = [c for c in pool.calls if c["url"].endswith("/purchase/sms")][0]
    assert buy["data"]["max_price"] == "0.60"
    assert buy["data"]["service"] == 907 and buy["data"]["country"] == "US"
    assert buy["data"]["key"] == KEY
    assert all(KEY not in str(c["params"]) for c in pool.calls)
    assert order.provider_order_id == "ABCDEFGH"
    assert order.phone_number == "+12025550123"
    assert order.state == ProviderOrderState.WAITING_FOR_CODE


@pytest.mark.parametrize("kind,operational", [("OUT_OF_STOCK", False), ("BALANCE_ERROR", True)])
def test_a_refused_purchase_raises(pool, kind, operational):
    pool.purchase = {"success": 0, "type": kind, "message": "<p>no</p>"}
    with pytest.raises(ProviderError) as caught:
        SMSPoolProvider().create_order("telegram", "US", "idem-1")
    assert caught.value.provider_code == kind
    assert caught.value.operational is operational


def test_a_code_is_proven_by_the_message(pool):
    pool.check = {"status": 3, "sms": "12345", "full_sms": "Your code is 12345",
                  "expiration": int(time.time()) + 600}
    status = SMSPoolProvider().get_order_status("ABCDEFGH")
    assert status.state == ProviderOrderState.CODE_RECEIVED
    assert status.code.code == "12345"


@pytest.mark.parametrize("check,state", [
    ({"status": 1, "expiration": int(time.time()) + 600}, ProviderOrderState.WAITING_FOR_CODE),
    ({"status": 6, "expiration": int(time.time()) + 600}, ProviderOrderState.CANCELLED),
    ({"status": 1, "expiration": int(time.time()) - 5}, ProviderOrderState.EXPIRED),
    ({"status": 9, "expiration": int(time.time()) + 600}, ProviderOrderState.WAITING_FOR_CODE),
    ({"status": 3, "expiration": int(time.time()) + 600}, ProviderOrderState.WAITING_FOR_CODE),
])
def test_statuses_without_a_message_never_read_as_delivered(pool, check, state):
    pool.check = check
    assert SMSPoolProvider().get_order_status("ABCDEFGH").state == state


def test_cancel_stock_and_balance(pool):
    provider = SMSPoolProvider()
    assert provider.cancel_order("ABCDEFGH") is True
    assert provider.get_availability("telegram", "US").count == 42
    assert provider.get_balance().available == Decimal("5.00")
    assert provider.health_check() is True


def test_without_a_key_nothing_is_bought(settings, monkeypatch):
    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS, "smspool": {}}
    provider = SMSPoolProvider()
    assert provider.is_configured is False
    assert provider.health_check() is False
