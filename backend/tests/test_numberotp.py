"""NumberOTP adapter, against a fake that answers like its published OpenAPI
file (numberotp.com/openapi.yaml)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.catalog.models import Service
from apps.common.errors import ProviderError
from apps.verification.base import ProviderOrderState
from apps.verification.numberotp import NumberOTPProvider, slug_for
from apps.verification.registry import available_adapters

pytestmark = pytest.mark.django_db

KEY = "notp_ci_only_not_real"


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeNumberOTP:
    def __init__(self):
        self.calls: list[dict] = []
        self.buy = ({"success": True, "data": {"id": "act_1", "phoneNumber": "12025550123",
                                               "expiresAt": "2026-11-23T15:30:00.000Z"},
                     "balance": 4.75}, 200)
        self.activation = {"id": "act_1", "status": "waiting", "otp": None, "full_sms": None,
                           "phone_number": "12025550123", "cost": 1.5,
                           "expires_at": "2026-11-23T15:30:00.000Z"}
        self.cancel_status = 200

    def __call__(self, method, url, json=None, params=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"method": method, "url": url, "json": json, "params": params,
                           "headers": dict(headers or {})})
        path = url.split("/v1", 1)[1]
        if path == "/public/services":
            return _Response({"success": True, "data": {"services": [
                {"code": "tg", "name": "Telegram"}, {"code": "ig", "name": "Instagram+Threads"},
                {"code": "fs:instagram", "name": "Instagram"}, {"code": "zz", "name": "Vercel"},
                {"code": "nn", "name": "Unpriced"}]}})
        if path == "/public/prices":
            return _Response({"success": True, "data": {"187": {
                "tg": {"cost": 1.5, "count": 68072}, "ig": {"cost": 0.26, "count": 96318},
                "fs:instagram": {"cost": 0.6, "count": 52}, "zz": {"cost": 0.05, "count": 9}}}})
        if path == "/activations" and method == "POST":
            return _Response(*self.buy)
        if path == "/activations/act_1":
            return _Response({"success": True, "data": self.activation})
        if path == "/activations/act_1/cancel":
            return _Response({"success": self.cancel_status == 200}, self.cancel_status)
        if path == "/me":
            return _Response({"success": True, "data": {"balance": 12.5, "on_hold": 1.5,
                                                        "currency": "USD"}})
        raise AssertionError(path)


@pytest.fixture
def notp(settings, monkeypatch):
    cache.clear()
    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "numberotp": {"api_key": KEY, "base_url": ""}}
    settings.VERIFYGH = {**settings.VERIFYGH, "MARKETPLACE_COUNTRIES": ["US"]}
    fake = FakeNumberOTP()
    monkeypatch.setattr("apps.verification.numberotp.requests.Session.request", fake)
    yield fake
    cache.clear()


def test_it_is_registered():
    assert "numberotp" in available_adapters()


@pytest.mark.parametrize("name,slug", [("Twitter/X", "twitter"), ("LinkedIN", "linkedin"),
                                       ("Google,youtube,Gmail", "google"),
                                       ("Instagram+Threads", "instagram"),
                                       ("Whatsapp", "whatsapp")])
def test_names_become_our_slugs(name, slug):
    assert slug_for(name) == slug


def test_the_catalogue_lists_priced_services_we_already_sell(notp):
    for slug in ("telegram", "instagram"):
        Service.objects.create(slug=slug, name=slug)
    offerings = {o.code: o for o in NumberOTPProvider().get_services()}
    assert set(offerings) == {"telegram", "instagram"}
    assert offerings["instagram"].cost == Decimal("0.26")       # the bigger of the two
    assert offerings["telegram"].available_count == 68072
    assert all(c["params"] == {"country": "187"} for c in notp.calls)


def test_an_order_is_idempotent_and_capped_at_the_listed_price(notp):
    order = NumberOTPProvider().create_order("telegram", "US", "idem-123")
    buy = notp.calls[-1]
    assert buy["headers"]["Idempotency-Key"] == "idem-123"
    assert buy["headers"]["Authorization"] == f"Bearer {KEY}"
    assert buy["json"] == {"service": "tg", "country": "187", "pool": "auto", "max_price": 1.5}
    assert order.provider_order_id == "act_1"
    assert order.phone_number == "+12025550123"
    assert order.state == ProviderOrderState.WAITING_FOR_CODE


@pytest.mark.parametrize("status,operational", [(402, True), (404, False)])
def test_a_refused_purchase_raises(notp, status, operational):
    notp.buy = ({"error": "no", "code": "X"}, status)
    with pytest.raises(ProviderError) as caught:
        NumberOTPProvider().create_order("telegram", "US", "idem-1")
    assert caught.value.operational is operational


def test_a_code_is_proven_by_the_otp(notp):
    notp.activation.update({"status": "received", "otp": "482910", "full_sms": "Code 482910"})
    status = NumberOTPProvider().get_order_status("act_1")
    assert status.state == ProviderOrderState.CODE_RECEIVED
    assert status.code.code == "482910"


@pytest.mark.parametrize("said,state", [("waiting", ProviderOrderState.WAITING_FOR_CODE),
                                        ("canceled", ProviderOrderState.CANCELLED),
                                        ("expired", ProviderOrderState.EXPIRED),
                                        ("received", ProviderOrderState.WAITING_FOR_CODE),
                                        ("finished", ProviderOrderState.WAITING_FOR_CODE)])
def test_statuses_without_an_otp_never_read_as_delivered(notp, said, state):
    notp.activation["status"] = said
    assert NumberOTPProvider().get_order_status("act_1").state == state


def test_cancel_and_balance(notp):
    provider = NumberOTPProvider()
    assert provider.cancel_order("act_1") is True
    notp.cancel_status = 409
    assert provider.cancel_order("act_1") is False
    balance = provider.get_balance()
    assert balance.available == Decimal("12.5") and balance.frozen == Decimal("1.5")


def test_only_the_us_is_offered(notp):
    with pytest.raises(ProviderError):
        NumberOTPProvider().get_pricing("telegram", "GB")
