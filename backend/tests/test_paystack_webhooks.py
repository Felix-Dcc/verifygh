"""Paystack webhook security, exercised through the real HTTP endpoint.

Earlier tests drove the mock adapter only, and missed that Paystack's signature
header never reached the verifier (Django title-cases header keys; the adapter
looked them up in lowercase). Every test here goes through `WebhookView`, with
`PAYMENT_PROVIDER=paystack`, so the production code path is what runs.

Signing follows Paystack's published scheme - HMAC-SHA512 of the raw request
body with the secret key, hex-encoded, in `x-paystack-signature`. The secret is
a throwaway test value; no real credential is used or needed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from apps.payments.models import Payment, PaymentStatus, PaymentWebhookEvent
from apps.wallet.models import WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

URL = "/api/v1/payments/webhooks/paystack/"
SECRET = "sk_test_ci_only_not_a_real_key"


@pytest.fixture(autouse=True)
def paystack_active(settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "paystack",
                         "WEBHOOK_PROVIDERS": []}
    settings.PAYMENT_CREDENTIALS = {
        **settings.PAYMENT_CREDENTIALS,
        "paystack": {"secret_key": SECRET, "base_url": "https://api.paystack.co"},
    }


@pytest.fixture
def payment(user):
    return Payment.objects.create(
        user=user, reference="VGH-PAY-PSTK0001", provider="paystack",
        amount=Decimal("50.00"), phone="+233241234567", network="MTN",
    )


def body(event="charge.success", *, reference="VGH-PAY-PSTK0001", amount=5000,
         currency="GHS", status="success", transaction_id=4099260516) -> bytes:
    payload = {
        "event": event,
        "data": {
            "id": transaction_id,
            "reference": reference,
            "amount": amount,           # pesewas
            "currency": currency,
            "status": status,
            "gateway_response": "Approved",
            "channel": "mobile_money",
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def sign(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()


def deliver(api, raw: bytes, signature: str | None = "auto"):
    headers = {}
    if signature == "auto":
        headers["HTTP_X_PAYSTACK_SIGNATURE"] = sign(raw)
    elif signature is not None:
        headers["HTTP_X_PAYSTACK_SIGNATURE"] = signature
    return api.post(URL, data=raw, content_type="application/json", **headers)


def balance(user) -> Decimal:
    return get_or_create_wallet(user).balance


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_a_correctly_signed_charge_success_credits_the_wallet(api, user, payment):
    """The regression test for the header-casing bug."""
    response = deliver(api, body())

    assert response.status_code == 200, response.data
    assert response.data["status"] == "processed"
    assert balance(user) == Decimal("50.00")  # 5000 pesewas
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS


def test_a_missing_signature_is_rejected(api, user, payment):
    assert deliver(api, body(), signature=None).status_code == 401
    assert balance(user) == Decimal("0.00")


def test_a_signature_from_another_secret_is_rejected(api, user, payment):
    raw = body()
    assert deliver(api, raw, signature=sign(raw, "sk_test_attacker")).status_code == 401
    assert balance(user) == Decimal("0.00")


def test_a_tampered_amount_is_rejected(api, user, payment):
    raw = body(amount=5000)
    tampered = raw.replace(b'"amount":5000', b'"amount":500000')
    assert deliver(api, tampered, signature=sign(raw)).status_code == 401
    assert balance(user) == Decimal("0.00")


def test_the_signature_covers_the_exact_bytes(api, user, payment):
    """Re-serialised JSON is a different message; it must not verify."""
    raw = body()
    reformatted = json.dumps(json.loads(raw), indent=2).encode("utf-8")
    assert deliver(api, reformatted, signature=sign(raw)).status_code == 401


# ---------------------------------------------------------------------------
# Idempotency and duplicates
# ---------------------------------------------------------------------------


def test_five_identical_paystack_webhooks_credit_once(api, user, payment):
    raw = body()
    results = [deliver(api, raw).data["status"] for _ in range(5)]

    assert results == ["processed"] + ["duplicate"] * 4
    assert balance(user) == Decimal("50.00")
    assert WalletLedgerEntry.objects.filter(wallet__user=user).count() == 1


def test_later_events_for_the_same_transaction_are_not_swallowed(api, user, payment):
    """Event ids used to be the transaction id alone, so the first event for a
    transaction silently dropped every later one - including the success."""
    first = deliver(api, body(event="charge.dispute.create", status="success"))
    second = deliver(api, body(event="charge.success"))

    assert first.data["status"] == "processed"
    assert second.data["status"] == "processed"  # not "duplicate"
    assert balance(user) == Decimal("50.00")
    assert PaymentWebhookEvent.objects.filter(provider="paystack").count() == 2


def test_the_same_event_under_a_new_transaction_id_still_credits_once(api, user, payment):
    """Different Paystack transaction ids for one of our payments: the ledger
    key is our payment reference, so the second is still refused."""
    deliver(api, body(transaction_id=1))
    deliver(api, body(transaction_id=2))

    assert balance(user) == Decimal("50.00")
    assert WalletLedgerEntry.objects.filter(wallet__user=user).count() == 1


# ---------------------------------------------------------------------------
# Transaction and reference validation
# ---------------------------------------------------------------------------


def test_a_reference_we_never_issued_credits_nothing(api, user, payment):
    response = deliver(api, body(reference="VGH-PAY-NOTOURS1"))
    assert response.status_code == 200
    assert balance(user) == Decimal("0.00")


@pytest.mark.parametrize("event", ["transfer.success", "refund.processed",
                                   "subscription.create", "invoice.update"])
def test_non_charge_events_never_confirm_a_deposit(api, user, payment, event):
    """Several Paystack events carry data.status == "success"."""
    response = deliver(api, body(event=event, status="success"))

    assert response.status_code == 200
    assert balance(user) == Decimal("0.00")
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
    assert payment.completed_at is None


def test_a_charge_in_another_currency_is_held_not_credited(api, user, payment):
    deliver(api, body(currency="USD"))

    assert balance(user) == Decimal("0.00")
    payment.refresh_from_db()
    assert payment.credited_at is None
    assert "Currency" in payment.failure_reason


def test_an_underpayment_credits_only_what_arrived(api, user, payment):
    deliver(api, body(amount=3000))
    assert balance(user) == Decimal("30.00")


def test_a_failed_charge_marks_the_payment_and_credits_nothing(api, user, payment):
    deliver(api, body(event="charge.failed", status="failed"))

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert balance(user) == Decimal("0.00")


def test_a_late_failure_cannot_reverse_a_credited_payment(api, user, payment):
    deliver(api, body(event="charge.success"))
    deliver(api, body(event="charge.failed", status="failed"))

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert balance(user) == Decimal("50.00")


def test_a_dispute_is_flagged_for_a_human_and_never_auto_reversed(api, user, payment):
    from apps.audit.models import SuspiciousActivity

    deliver(api, body(event="charge.success"))
    deliver(api, body(event="charge.dispute.create", status="success"))

    assert balance(user) == Decimal("50.00")
    assert SuspiciousActivity.objects.filter(
        user=user, kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY, level="HIGH"
    ).exists()


def test_a_mock_payment_cannot_be_settled_through_the_paystack_endpoint(api, user):
    mock_payment = Payment.objects.create(
        user=user, reference="VGH-PAY-MOCKONE1", provider="mock",
        amount=Decimal("50.00"), phone="+233241234567", network="MTN",
    )
    deliver(api, body(reference=mock_payment.reference))
    assert balance(user) == Decimal("0.00")


# ---------------------------------------------------------------------------
# The frontend can never confirm a payment
# ---------------------------------------------------------------------------


def test_no_endpoint_lets_a_client_set_a_payment_status(user, auth, payment):
    client = auth(user)
    for method in ("put", "patch", "post"):
        response = getattr(client, method)(
            f"/api/v1/payments/{payment.reference}/",
            {"status": "SUCCESS", "credited_at": "2026-01-01T00:00:00Z"}, format="json",
        )
        assert response.status_code == 405, method

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
    assert balance(user) == Decimal("0.00")


def test_a_deposit_request_cannot_carry_its_own_success(user, auth, settings):
    """Extra fields a client sends are ignored; the charge starts PENDING."""
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "mock"}
    client = auth(user)
    response = client.post(
        "/api/v1/payments/deposit/",
        {"amount": "50.00", "phone": "0241234567", "status": "SUCCESS", "credited": True},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["status"] in ("PENDING", "PROCESSING")
    assert balance(user) == Decimal("0.00")


def test_refresh_asks_paystack_and_obeys_its_answer(user, auth, payment, monkeypatch):
    """The client may ask us to re-check; only Paystack's own answer counts.
    Uses Paystack's documented verify-transaction call, with the network mocked."""
    import requests

    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, status):
            self._status = status

        def json(self):
            return {"status": True, "data": {"status": self._status, "amount": 5000,
                                             "currency": "GHS",
                                             "reference": "VGH-PAY-PSTK0001"}}

    answer = {"status": "abandoned"}

    def fake_request(self, method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(answer["status"])

    monkeypatch.setattr(requests.Session, "request", fake_request)
    client = auth(user)

    client.post(f"/api/v1/payments/{payment.reference}/refresh/", {}, format="json")
    assert balance(user) == Decimal("0.00")  # Paystack said no

    Payment.objects.filter(pk=payment.pk).update(status=PaymentStatus.PENDING,
                                                 completed_at=None)
    answer["status"] = "success"
    client.post(f"/api/v1/payments/{payment.reference}/refresh/", {}, format="json")
    assert balance(user) == Decimal("50.00")  # Paystack said yes

    assert all(url.endswith("/transaction/verify/VGH-PAY-PSTK0001") for _, url in calls)
