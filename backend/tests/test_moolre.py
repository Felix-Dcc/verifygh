"""Moolre Mobile Money, through VerifyGH's real deposit and webhook paths.

8 Oct 2026: Paystack disabled the business, and Moolre (BoG-licensed) takes
over collections. The fake below answers the way Moolre's sandbox did on that
day: TP14 asks a first-time payer for an SMS code, the same externalref is
resent with the code (TP17, or TP15 when wrong), and once more without it to
send the prompt (TR099). The status endpoint is the only thing trusted.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from apps.common.errors import ProviderError, ValidationFailed
from apps.payments.models import Payment, PaymentStatus
from apps.payments.moolre import MoolreProvider, local_number
from apps.payments.services import initiate_deposit, reconcile_payment, submit_deposit_otp
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

ACCOUNT = "10000000001"
SECRET = "ci-callback-secret-not-real"
URL = "/api/v1/payments/webhooks/moolre/"
CODE = "123456"


class FakeMoolre:
    """Moolre's collection and status endpoints, as the sandbox behaved."""

    def __init__(self):
        self.calls: list[dict] = []
        self.first_time: set[str] = set()   # payers who must verify by SMS first
        self.verified: set[str] = set()
        self.tx: dict[str, dict] = {}       # externalref -> {"txstatus", "amount"}

    def __call__(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "body": dict(json or {}), "headers": dict(headers or {})})
        if url.endswith("/open/transact/payment"):
            return _Response(self.collect(json))
        if url.endswith("/open/transact/status"):
            return _Response(self.status(json))
        raise AssertionError(url)

    def collect(self, body):
        payer, ref = body["payer"], body["externalref"]
        if payer in self.first_time and payer not in self.verified:
            if not body.get("otpcode"):
                return {"status": 1, "code": "TP14", "message": "verify by SMS", "data": "all"}
            if body["otpcode"] != CODE:
                return {"status": 0, "code": "TP15", "message": "Invalid code", "data": "otpcode"}
            self.verified.add(payer)
            return {"status": 1, "code": "TP17", "message": "verified", "data": None}
        self.tx.setdefault(ref, {"txstatus": 0, "amount": body["amount"]})
        return {"status": 1, "code": "TR099", "message": None, "data": "moolre-uuid-1"}

    def status(self, body):
        tx = self.tx.get(body["id"])
        if tx is None:
            return {"status": 0, "code": "ST09", "message": "Not found", "data": None}
        return {"status": 1, "code": "SS01", "message": "ok", "data": {
            "txstatus": tx["txstatus"], "txtype": 1, "accountnumber": ACCOUNT,
            "amount": tx["amount"], "value": tx["amount"], "transactionid": "4156",
            "externalref": body["id"], "reason": tx.get("reason", "")}}


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def moolre(settings, monkeypatch):
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "moolre",
                         "WEBHOOK_PROVIDERS": [], "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS, "moolre": {
        "username": "verifygh", "public_key": "pub-ci-only", "account_number": ACCOUNT,
        "callback_secret": SECRET, "base_url": "https://api.moolre.com"}}
    fake = FakeMoolre()
    monkeypatch.setattr("apps.payments.moolre.requests.Session.post", fake)
    return fake


def deposit(user, phone="+233241234567", network="MTN", amount="10.00"):
    return initiate_deposit(user=user, amount=Decimal(amount), phone=phone, network=network)


def callback(api, reference, *, code="P01", txstatus=1, amount="10.00", secret=SECRET):
    body = {"status": 1 if code == "P01" else 0, "code": code, "message": "x", "data": {
        "txstatus": txstatus, "payer": "233241234567", "accountnumber": ACCOUNT,
        "amount": amount, "value": amount, "transactionid": "4156", "externalref": reference,
        "secret": secret, "ts": "2026-10-08 11:00:00"}}
    return api.post(URL, data=json.dumps(body), content_type="application/json")


# -- collection ---------------------------------------------------------------


def test_a_repeat_payer_gets_the_prompt_straight_away(moolre, user):
    payment = deposit(user)
    assert payment.status == PaymentStatus.PHONE_AUTH
    assert "Mobile Money PIN" in payment.instructions
    call = moolre.calls[0]
    assert call["body"] == {"type": 1, "channel": "13", "currency": "GHS", "payer": "0241234567",
                            "amount": "10.00", "externalref": payment.reference,
                            "accountnumber": ACCOUNT}
    assert call["headers"]["X-API-USER"] == "verifygh"
    assert call["headers"]["X-API-PUBKEY"] == "pub-ci-only"


@pytest.mark.parametrize("network,channel", [("MTN", "13"), ("TELECEL", "6"), ("AT", "7")])
def test_each_network_uses_its_channel(moolre, user, network, channel):
    deposit(user, phone="+233201234567", network=network)
    assert moolre.calls[0]["body"]["channel"] == channel


def test_a_first_time_payer_verifies_by_sms_then_gets_the_prompt(moolre, user):
    moolre.first_time.add("0241234567")
    payment = deposit(user)
    assert payment.status == PaymentStatus.OTP_REQUIRED

    payment = submit_deposit_otp(user=user, reference=payment.reference, otp=CODE)
    assert payment.status == PaymentStatus.PHONE_AUTH
    bodies = [c["body"] for c in moolre.calls]
    assert bodies[1]["otpcode"] == CODE and bodies[1]["externalref"] == payment.reference
    assert "otpcode" not in bodies[2] and bodies[2]["externalref"] == payment.reference


def test_a_wrong_sms_code_is_refused(moolre, user):
    moolre.first_time.add("0241234567")
    payment = deposit(user)
    with pytest.raises(ValidationFailed) as raised:
        submit_deposit_otp(user=user, reference=payment.reference, otp="999999")
    assert raised.value.code == "OTP_REJECTED"
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.OTP_REQUIRED


def test_a_refused_collection_fails_the_payment_and_says_nothing_of_moolre(moolre, user,
                                                                           monkeypatch):
    monkeypatch.setattr(moolre, "collect", lambda body: {"status": 0, "code": "TP01",
                                                         "message": "Currency Invalid"})
    with pytest.raises(ProviderError) as raised:
        deposit(user)
    assert "Currency" not in str(raised.value)
    assert Payment.objects.get().status == PaymentStatus.FAILED


@pytest.mark.parametrize("raw,local", [("+233241234567", "0241234567"),
                                       ("233241234567", "0241234567"),
                                       ("0241234567", "0241234567")])
def test_numbers_are_sent_in_the_local_format(raw, local):
    assert local_number(raw) == local


# -- callbacks are prompts; the status endpoint decides ----------------------------


def test_a_confirmed_callback_credits_the_wallet_once(moolre, user, api):
    payment = deposit(user)
    moolre.tx[payment.reference]["txstatus"] = 1
    assert callback(api, payment.reference).status_code == 200
    assert callback(api, payment.reference).status_code == 200  # Moolre may resend
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_a_callback_the_status_endpoint_does_not_confirm_credits_nothing(moolre, user, api):
    """Moolre callbacks carry only a static secret. One claiming success while
    the payment is still pending - forged, or early - must not move money."""
    payment = deposit(user)
    callback(api, payment.reference)  # claims P01; status still says pending
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PHONE_AUTH
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_the_amount_comes_from_the_status_endpoint_not_the_callback(moolre, user, api):
    payment = deposit(user)
    moolre.tx[payment.reference]["txstatus"] = 1
    callback(api, payment.reference, amount="500.00")
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_a_wrong_secret_is_refused(moolre, user, api):
    payment = deposit(user)
    moolre.tx[payment.reference]["txstatus"] = 1
    callback(api, payment.reference, secret="guessed")
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PHONE_AUTH
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_confirmed_failure_fails_the_payment(moolre, user, api):
    payment = deposit(user)
    moolre.tx[payment.reference].update(txstatus=2, reason="LOW_BALANCE")
    callback(api, payment.reference, code="P02", txstatus=2, amount="0")
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_reconciliation_credits_a_payment_whose_callback_never_came(moolre, user):
    payment = deposit(user)
    moolre.tx[payment.reference]["txstatus"] = 1
    payment = reconcile_payment(payment)
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_a_status_answer_for_another_payment_is_refused(moolre, monkeypatch):
    monkeypatch.setattr(moolre, "status", lambda body: {"status": 1, "code": "SS01", "data": {
        "txstatus": 1, "amount": "10.00", "externalref": "someone-else"}})
    with pytest.raises(ProviderError):
        MoolreProvider().fetch_charge("VGH-PAY-MINE")


def test_the_deposit_form_warns_about_the_network_fee(moolre, api):
    note = api.get("/api/v1/payments/options/").data["fee_note"]
    assert "1%" in note and "full amount" in note
