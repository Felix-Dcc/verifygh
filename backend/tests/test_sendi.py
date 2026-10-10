"""SENDI hosted checkout, through VerifyGH's real deposit and webhook paths.

8 Oct 2026: a stopgap while Moolre approves the wallet. The fake answers the
way SENDI's Merchant API docs describe: initialize returns a ch_ reference and
an authorization_url on mesendi.com, verify reports the charge, and webhooks
are signed with a hex HMAC-SHA512 of the raw body. Only verify is trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from apps.common.errors import ProviderError
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import initiate_deposit, reconcile_payment
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

SECRET_KEY = "sk_live_ci_only_not_real"
SIGNING = "ci-signing-secret-not-real"
URL = "/api/v1/payments/webhooks/sendi/"


class FakeSendi:
    def __init__(self):
        self.calls: list[dict] = []
        self.charges: dict[str, dict] = {}   # ch_ reference -> verify data
        self.checkout_host = "mesendi.com"

    def __call__(self, method, url, json=None, params=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"method": method, "url": url, "body": json, "params": params,
                           "headers": dict(headers or {})})
        if url.endswith("/api/v1/charge/initialize"):
            ref = f"ch_live_{len(self.charges):020d}"
            self.charges[ref] = {"reference": ref, "status": "pending",
                                 "amount_cents": json["amount_cents"], "currency": "GHS"}
            return _Response({"success": True, "data": {
                "reference": ref, "status": "pending", "amount_cents": json["amount_cents"],
                "authorization_url": f"https://{self.checkout_host}/checkout/{ref}"}})
        if url.endswith("/api/v1/charge/verify"):
            charge = self.charges.get(params["reference"])
            if charge is None:
                return _Response({"success": False, "message": "Not found"}, 404)
            return _Response({"success": True, "data": dict(charge)})
        raise AssertionError(url)


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture
def sendi(settings, monkeypatch):
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "sendi",
                         "WEBHOOK_PROVIDERS": [], "REQUIRE_CATALOG_FOR_DEPOSIT": False,
                         "FRONTEND_URL": "https://www.getverifygh.com"}
    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS, "sendi": {
        "secret_key": SECRET_KEY, "webhook_secret": SIGNING,
        "base_url": "https://mesendi.com/backend"}}
    fake = FakeSendi()
    monkeypatch.setattr("apps.payments.sendi.requests.Session.request", fake)
    return fake


def deposit(user, amount="10.00"):
    return initiate_deposit(user=user, amount=Decimal(amount), phone="+233241234567",
                            network="MTN")


def webhook(api, body: dict, secret=SIGNING):
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    return api.post(URL, data=raw, content_type="application/json",
                    HTTP_X_SENDI_SIGNATURE=signature)


# -- starting a charge --------------------------------------------------------


def test_a_deposit_sends_the_customer_to_sendi_checkout(sendi, user, auth):
    payment = deposit(user)
    assert payment.status == PaymentStatus.PENDING
    assert payment.provider_reference.startswith("ch_live_")

    call = sendi.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {SECRET_KEY}"
    assert call["headers"]["Idempotency-Key"] == payment.reference
    assert call["body"]["amount_cents"] == 1000 and call["body"]["currency"] == "GHS"
    assert call["body"]["callback_url"] == (
        f"https://www.getverifygh.com/wallet/deposit?reference={payment.reference}")
    assert call["body"]["metadata"] == {"reference": payment.reference}

    shown = auth(user).get(f"/api/v1/payments/{payment.reference}/").data
    assert shown["checkout_url"] == f"https://mesendi.com/checkout/{payment.provider_reference}"


def test_a_checkout_on_another_host_is_refused(sendi, user):
    sendi.checkout_host = "mesendi.com.evil.example"
    with pytest.raises(ProviderError):
        deposit(user)
    assert Payment.objects.get().status == PaymentStatus.FAILED


# -- settling -----------------------------------------------------------------


def test_verify_success_credits_the_wallet_once(sendi, user):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "success"
    reconcile_payment(payment)
    reconcile_payment(Payment.objects.get(pk=payment.pk))
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_the_checkout_link_is_gone_once_settled(sendi, user, auth):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "success"
    reconcile_payment(payment)
    assert auth(user).get(f"/api/v1/payments/{payment.reference}/").data["checkout_url"] == ""


@pytest.mark.parametrize("change", [
    {"test_mode": True},                 # a test charge, on a live key
    {"currency": "USD"},
    {"amount_cents": None},
    {"reference": "ch_live_someone_else"},
])
def test_a_doubtful_success_is_held_not_credited(sendi, user, change):
    payment = deposit(user)
    sendi.charges[payment.provider_reference].update({"status": "success", **change})
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status != PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_failed_charge_fails_the_payment(sendi, user):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "failed"
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_an_unknown_status_changes_nothing(sendi, user):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "reversed-maybe"
    reconcile_payment(payment)
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


# -- webhooks -----------------------------------------------------------------


def test_a_signed_webhook_is_confirmed_by_verify(sendi, user, api):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "success"
    response = webhook(api, {"event": "charge.success",
                             "data": {"reference": payment.provider_reference}})
    assert response.status_code == 200, response.data
    assert get_or_create_wallet(user).balance == Decimal("10.00")
    # A retry of the same event is a no-op.
    webhook(api, {"event": "charge.success", "data": {"reference": payment.provider_reference}})
    assert get_or_create_wallet(user).balance == Decimal("10.00")


def test_a_webhook_saying_success_is_not_believed(sendi, user, api):
    payment = deposit(user)  # verify still says pending
    response = webhook(api, {"event": "charge.success", "data": {
        "reference": payment.provider_reference, "status": "success", "amount_cents": 1000}})
    assert response.status_code == 200
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_badly_signed_webhook_is_rejected(sendi, user, api):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "success"
    response = webhook(api, {"data": {"reference": payment.provider_reference}},
                       secret="wrong-secret")
    assert response.status_code == 401
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_webhook_found_by_our_reference_in_metadata(sendi, user, api):
    payment = deposit(user)
    sendi.charges[payment.provider_reference]["status"] = "success"
    webhook(api, {"event": "charge.success",
                  "data": {"metadata": {"reference": payment.reference}}})
    assert get_or_create_wallet(user).balance == Decimal("10.00")


# -- retrying a checkout ------------------------------------------------------


def initializes(fake) -> int:
    return sum(1 for call in fake.calls if call["url"].endswith("/charge/initialize"))


def test_tapping_pay_again_reopens_the_open_checkout(sendi, user):
    """9 Oct: three retries made three unfinished checkouts and a flag."""
    first = deposit(user, "14.00")
    again = deposit(user, "14.00")
    assert again.reference == first.reference
    assert initializes(sendi) == 1
    assert Payment.objects.filter(user=user).count() == 1


def test_retrying_never_trips_the_unfinished_payments_limit(sendi, user):
    from apps.audit.models import SuspiciousActivity

    for _ in range(5):
        deposit(user, "14.00")
    assert Payment.objects.filter(user=user).count() == 1
    assert not SuspiciousActivity.objects.filter(user=user).exists()


def test_a_checkout_sendi_has_failed_is_not_reopened(sendi, user):
    first = deposit(user, "14.00")
    sendi.charges[first.provider_reference]["status"] = "failed"
    again = deposit(user, "14.00")
    assert again.reference != first.reference
    assert Payment.objects.get(pk=first.pk).status == PaymentStatus.FAILED
    assert initializes(sendi) == 2


def test_a_different_amount_gets_its_own_checkout(sendi, user):
    first = deposit(user, "14.00")
    other = deposit(user, "13.00")
    assert other.reference != first.reference
    assert initializes(sendi) == 2
