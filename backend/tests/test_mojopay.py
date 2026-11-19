"""MojoPay Omni mobile money, through VerifyGH's real deposit and webhook paths.

The fake answers the way MojoPay's OpenAPI spec and sample payloads describe:
an OAuth token, POST /v1/collections returning a CL_ collection in
"processing", GET /v1/collections?merchant_reference=..., and webhooks signed
"t=<unix>,v1=<hex HMAC-SHA256 of t.body>". Only the GET is trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import initiate_deposit, reconcile_payment
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

SIGNING = "ci-signing-secret-not-real"
URL = "/api/v1/payments/webhooks/mojopay/"


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeMojoPay:
    def __init__(self):
        self.calls: list[dict] = []
        self.tokens_issued = 0
        self.collections: dict[str, dict] = {}   # merchant_reference -> collection
        self.reject_token_once = False

    def __call__(self, method, url, json=None, params=None, headers=None, timeout=None):  # noqa: A002
        headers = dict(headers or {})
        self.calls.append({"method": method, "url": url, "body": json, "params": params,
                           "headers": headers})
        if url.endswith("/v1/oauth/token"):
            assert json["client_id"] == "client-ci" and json["client_secret"] == "secret-ci"
            self.tokens_issued += 1
            return _Response({"access_token": f"tok{self.tokens_issued}", "token_type": "Bearer",
                              "expires_in": 1200})
        if self.reject_token_once:
            self.reject_token_once = False
            return _Response({"error": {"code": "unauthorized", "message": "x",
                                        "request_id": "REQ_A"}}, 401)
        if method == "POST" and url.endswith("/v1/collections"):
            ref = json["merchant_reference"]
            self.collections[ref] = {"id": f"CL_{len(self.collections):010d}",
                                     "object": "collection",
                                     "status": "processing", "currency": json["currency"],
                                     "amount": json["amount"], "merchant_reference": ref}
            return _Response(dict(self.collections[ref]), 201)
        if method == "GET" and url.endswith("/v1/collections"):
            found = self.collections.get(params["merchant_reference"])
            if found is None:
                return _Response({"error": {"code": "not_found", "message": "x",
                                            "request_id": "REQ_B"}}, 404)
            return _Response(dict(found))
        raise AssertionError(url)


@pytest.fixture
def mojopay(settings, monkeypatch):
    cache.delete("payments:mojopay:token")
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "mojopay",
                         "WEBHOOK_PROVIDERS": [], "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS, "mojopay": {
        "client_id": "client-ci", "client_secret": "secret-ci", "webhook_secret": SIGNING,
        "base_url": "https://omni.mojo-pay.com"}}
    fake = FakeMojoPay()
    monkeypatch.setattr("apps.payments.mojopay.requests.Session.request", fake)
    yield fake
    cache.delete("payments:mojopay:token")


def deposit(user, amount="10.00", network="MTN", phone="+233241234567"):
    return initiate_deposit(user=user, amount=Decimal(amount), phone=phone, network=network)


def webhook(api, body: dict, secret=SIGNING, stamp=None):
    raw = json.dumps(body).encode()
    t = str(stamp if stamp is not None else int(time.time()))
    v1 = hmac.new(secret.encode(), t.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return api.post(URL, data=raw, content_type="application/json",
                    HTTP_MOJOPAY_SIGNATURE=f"t={t},v1={v1}")


def event(payment, kind="collection.succeeded"):
    return {"id": "EVT_" + "A" * 24, "type": kind, "data": {"object": {
        "id": payment.provider_reference, "object": "collection",
        "status": kind.split(".")[1], "merchant_reference": payment.reference}}}


# -- starting a charge --------------------------------------------------------


def test_a_deposit_sends_a_prompt_to_the_phone(mojopay, user):
    payment = deposit(user)
    assert payment.status == PaymentStatus.PHONE_AUTH
    assert payment.provider_reference.startswith("CL_")

    call = mojopay.calls[-1]
    assert call["headers"]["Authorization"] == "Bearer tok1"
    assert call["headers"]["Idempotency-Key"] == payment.reference
    assert call["body"] == {"amount": "10.00", "currency": "GHS",
                            "merchant_reference": payment.reference, "mobile": "233241234567",
                            "provider": "MTN",
                            "description": f"VerifyGH wallet top-up {payment.reference}"}


@pytest.mark.parametrize("network,code", [("TELECEL", "VODAFONE"), ("AT", "AIRTELTIGO")])
def test_networks_use_mojopays_provider_codes(mojopay, user, network, code):
    phone = {"TELECEL": "+233201234567", "AT": "+233271234567"}[network]
    deposit(user, network=network, phone=phone)
    assert mojopay.calls[-1]["body"]["provider"] == code


def test_the_token_is_reused_and_renewed_when_refused(mojopay, user):
    deposit(user)
    deposit(user)
    assert mojopay.tokens_issued == 1
    mojopay.reject_token_once = True
    deposit(user)
    assert mojopay.tokens_issued == 2


# -- settling -----------------------------------------------------------------


def test_success_credits_the_wallet_once(mojopay, user):
    payment = deposit(user)
    mojopay.collections[payment.reference]["status"] = "succeeded"
    reconcile_payment(payment)
    reconcile_payment(Payment.objects.get(pk=payment.pk))
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("10.00")


@pytest.mark.parametrize("change", [
    {"currency": "USD"},
    {"amount": None},
    {"merchant_reference": "VGH-PAY-SOMEONEELSE"},
])
def test_a_doubtful_success_is_held_not_credited(mojopay, user, change):
    payment = deposit(user)
    mojopay.collections[payment.reference].update({"status": "succeeded", **change})
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status != PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_failed_collection_fails_the_payment(mojopay, user):
    payment = deposit(user)
    mojopay.collections[payment.reference].update({"status": "failed",
                                                   "status_detail": "Insufficient balance"})
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_collection_mojopay_cannot_find_is_left_pending(mojopay, user):
    payment = deposit(user)
    del mojopay.collections[payment.reference]
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status not in (PaymentStatus.SUCCESS, PaymentStatus.FAILED)


# -- webhooks -----------------------------------------------------------------


def test_a_signed_webhook_is_confirmed_by_mojopay(mojopay, user, api):
    payment = deposit(user)
    mojopay.collections[payment.reference]["status"] = "succeeded"
    assert webhook(api, event(payment)).status_code == 200
    assert webhook(api, event(payment)).status_code == 200   # at-least-once delivery
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_a_webhook_claiming_success_is_not_believed(mojopay, user, api):
    payment = deposit(user)   # MojoPay itself still says "processing"
    webhook(api, event(payment))
    payment.refresh_from_db()
    assert payment.status != PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("0.00")


@pytest.mark.parametrize("kwargs", [{"secret": "wrong-secret"},
                                    {"stamp": int(time.time()) - 301}])
def test_a_forged_or_stale_webhook_is_rejected(mojopay, user, api, kwargs):
    payment = deposit(user)
    mojopay.collections[payment.reference]["status"] = "succeeded"
    response = webhook(api, event(payment), **kwargs)
    assert response.status_code in (400, 401, 403)
    assert get_or_create_wallet(user).balance == Decimal("0.00")
