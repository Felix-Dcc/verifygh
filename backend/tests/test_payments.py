"""Deposits and webhooks.

The headline test is `test_five_identical_webhooks_credit_once`: the spec calls
it out, and it is the difference between a payment platform and a liability.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.payments.mock import build_webhook, sign
from apps.payments.models import Payment, PaymentStatus, PaymentWebhookEvent
from apps.wallet.models import WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/v1/payments/webhooks/mock/"


def start_deposit(client, amount="50.00", phone="0241234567"):
    return client.post(
        "/api/v1/payments/deposit/",
        {"amount": amount, "phone": phone},
        format="json",
    )


def post_webhook(api, raw_body, headers):
    return api.post(
        WEBHOOK_URL,
        data=raw_body,
        content_type="application/json",
        **{"HTTP_X_MOCK_SIGNATURE": headers["X-Mock-Signature"]},
    )


# ---------------------------------------------------------------------------
# Initiating
# ---------------------------------------------------------------------------


def test_deposit_creates_a_pending_payment_and_credits_nothing(user, auth):
    client = auth(user)
    response = start_deposit(client)

    assert response.status_code == 201, response.data
    assert response.data["status"] in ("PENDING", "PROCESSING")
    assert response.data["reference"].startswith("VGH-PAY-")

    # Critically: starting a payment does not move money.
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_network_is_inferred_from_the_phone_prefix(user, auth):
    client = auth(user)

    assert start_deposit(client, phone="0241234567").data["network"] == "MTN"
    assert start_deposit(client, phone="0201234567").data["network"] == "TELECEL"


def test_deposit_below_the_minimum_is_rejected(user, auth):
    client = auth(user)
    response = start_deposit(client, amount="1.00")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_ghanaian_number_is_rejected(user, auth):
    client = auth(user)
    response = start_deposit(client, phone="12345")
    assert response.status_code == 400


def test_deposit_requires_authentication(api):
    response = start_deposit(api)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def test_successful_webhook_credits_the_wallet(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "75.00").data["reference"]

    raw_body, headers = build_webhook(reference=reference, amount="75.00")
    response = post_webhook(api, raw_body, headers)

    assert response.status_code == 200
    assert response.data["status"] == "processed"

    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("75.00")

    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.credited_at is not None
    assert payment.ledger_entry_id is not None


def test_five_identical_webhooks_credit_once(user, auth, api):
    """The test the spec asks for by name."""
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    raw_body, headers = build_webhook(
        reference=reference, amount="50.00", event_id="evt_fixed_id"
    )

    statuses = [post_webhook(api, raw_body, headers) for _ in range(5)]

    assert [response.status_code for response in statuses] == [200] * 5
    assert statuses[0].data["status"] == "processed"
    assert [response.data["status"] for response in statuses[1:]] == ["duplicate"] * 4

    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("50.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1
    assert PaymentWebhookEvent.objects.filter(event_id="evt_fixed_id").count() == 1


def test_distinct_events_for_the_same_payment_still_credit_once(user, auth, api):
    """Different event ids, same payment: the ledger key is the payment, so the
    second one is still refused."""
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    for index in range(3):
        raw_body, headers = build_webhook(
            reference=reference, amount="50.00", event_id=f"evt_{index}"
        )
        assert post_webhook(api, raw_body, headers).status_code == 200

    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("50.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1


def test_unsigned_webhook_is_rejected_and_credits_nothing(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    raw_body, _headers = build_webhook(reference=reference, amount="50.00")
    response = api.post(WEBHOOK_URL, data=raw_body, content_type="application/json")

    assert response.status_code == 401
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_tampered_webhook_body_is_rejected(user, auth, api):
    """A forged amount invalidates the signature over the raw bytes."""
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    raw_body, headers = build_webhook(reference=reference, amount="50.00")
    tampered = raw_body.replace(b'"50.00"', b'"5000.00"')

    response = post_webhook(api, tampered, headers)

    assert response.status_code == 401
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_signature_from_the_wrong_secret_is_rejected(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]
    raw_body, _ = build_webhook(reference=reference, amount="50.00")

    response = post_webhook(api, raw_body, {"X-Mock-Signature": "0" * 128})

    assert response.status_code == 401
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_failed_webhook_marks_the_payment_and_credits_nothing(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    raw_body, headers = build_webhook(
        reference=reference, amount="50.00", status="FAILED",
        failure_reason="Insufficient funds on the MoMo wallet.",
    )
    assert post_webhook(api, raw_body, headers).status_code == 200

    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.FAILED
    assert payment.credited_at is None
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_late_failure_webhook_cannot_undo_a_successful_payment(user, auth, api):
    """A settled payment never walks backwards on a late callback."""
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    success_body, success_headers = build_webhook(reference=reference, amount="50.00")
    post_webhook(api, success_body, success_headers)

    failure_body, failure_headers = build_webhook(
        reference=reference, amount="50.00", status="FAILED", event_id="evt_late_failure"
    )
    post_webhook(api, failure_body, failure_headers)

    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("50.00")


def test_webhook_for_an_unknown_reference_is_recorded_but_credits_nothing(api, user):
    raw_body, headers = build_webhook(reference="VGH-PAY-NOTREAL", amount="500.00")
    response = post_webhook(api, raw_body, headers)

    assert response.status_code == 200
    assert get_or_create_wallet(user).balance == Decimal("0.00")
    assert PaymentWebhookEvent.objects.filter(reference="VGH-PAY-NOTREAL").exists()


def test_amount_mismatch_credits_what_actually_arrived_and_flags_it(user, auth, api):
    """Under-payment credits the real amount, never the requested one."""
    from apps.audit.models import SuspiciousActivity

    client = auth(user)
    reference = start_deposit(client, "100.00").data["reference"]

    raw_body, headers = build_webhook(reference=reference, amount="40.00")
    post_webhook(api, raw_body, headers)

    assert get_or_create_wallet(user).balance == Decimal("40.00")
    assert SuspiciousActivity.objects.filter(
        user=user, kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY
    ).exists()


def test_webhook_signature_covers_exact_bytes(user):
    """Re-serialising the payload changes the digest - so we sign raw bytes."""
    raw_body, headers = build_webhook(reference="VGH-PAY-ABC", amount="10.00")
    reserialised = raw_body.replace(b",", b", ")
    assert sign(raw_body) == headers["X-Mock-Signature"]
    assert sign(reserialised) != headers["X-Mock-Signature"]


# ---------------------------------------------------------------------------
# Anti-abuse
# ---------------------------------------------------------------------------


def test_stacking_up_unapproved_prompts_is_blocked(user, auth):
    client = auth(user)
    for _ in range(3):
        assert start_deposit(client, "10.00").status_code == 201

    response = start_deposit(client, "10.00")
    assert response.status_code == 429
    assert response.data["error"]["code"] == "TOO_MANY_PENDING_DEPOSITS"


def test_deposit_cannot_push_balance_past_the_cap(user, auth, funded_wallet, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_WALLET_BALANCE": "100.00"}
    funded_wallet(user, "95.00")
    client = auth(user)

    response = start_deposit(client, "20.00")
    assert response.status_code == 429
    assert response.data["error"]["code"] == "WALLET_CAP_EXCEEDED"


# ---------------------------------------------------------------------------
# Recovery when processing fails
# ---------------------------------------------------------------------------


def test_a_failed_webhook_is_reapplied_when_the_provider_retries(user, auth, api, monkeypatch):
    """The worst failure mode: recorded, not applied, never retried.

    If the first delivery records the event and then blows up, answering the
    provider's retry with "duplicate" would leave the customer permanently
    uncredited. The retry must actually do the work.
    """
    from apps.payments import services

    client = auth(user)
    reference = start_deposit(client, "80.00").data["reference"]
    raw_body, headers = build_webhook(reference=reference, amount="80.00",
                                      event_id="evt_transient_failure")

    original = services._apply_event
    calls = {"n": 0}

    def flaky(event, provider_key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away")
        return original(event, provider_key)

    monkeypatch.setattr(services, "_apply_event", flaky)

    # First delivery fails. The endpoint answers 5xx, which is what makes the
    # provider retry rather than considering the callback delivered.
    first = post_webhook(api, raw_body, headers)
    assert first.status_code == 500
    assert first.data["error"]["code"] == "INTERNAL_ERROR"

    assert get_or_create_wallet(user).balance == Decimal("0.00")
    event = PaymentWebhookEvent.objects.get(event_id="evt_transient_failure")
    assert event.processed is False
    assert "database went away" in event.processing_error

    # The provider retries the identical event.
    response = post_webhook(api, raw_body, headers)

    assert response.status_code == 200
    assert response.data["status"] == "processed"
    assert get_or_create_wallet(user).balance == Decimal("80.00")

    event.refresh_from_db()
    assert event.processed is True


def test_the_sweep_recovers_a_webhook_the_provider_gave_up_on(user, auth, api, monkeypatch):
    """Providers stop retrying. Recovery cannot depend on them."""
    from apps.payments import services
    from apps.payments.tasks import retry_failed_webhooks

    client = auth(user)
    reference = start_deposit(client, "65.00").data["reference"]
    raw_body, headers = build_webhook(reference=reference, amount="65.00",
                                      event_id="evt_abandoned")

    original = services._apply_event
    calls = {"n": 0}

    def fail_once(event, provider_key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return original(event, provider_key)

    monkeypatch.setattr(services, "_apply_event", fail_once)

    assert post_webhook(api, raw_body, headers).status_code == 500
    assert get_or_create_wallet(user).balance == Decimal("0.00")

    # No further delivery from the provider - the scheduled sweep finishes it.
    result = retry_failed_webhooks()

    assert result["replayed"] == 1
    assert get_or_create_wallet(user).balance == Decimal("65.00")


def test_replaying_an_already_applied_webhook_does_not_double_credit(user, auth, api):
    """Re-application has to be safe, or the retry fix would be worse than the bug."""
    from apps.payments.services import replay_failed_webhook

    client = auth(user)
    reference = start_deposit(client, "40.00").data["reference"]
    raw_body, headers = build_webhook(reference=reference, amount="40.00",
                                      event_id="evt_replay_safety")
    post_webhook(api, raw_body, headers)
    assert get_or_create_wallet(user).balance == Decimal("40.00")

    record = PaymentWebhookEvent.objects.get(event_id="evt_replay_safety")
    # Pretend the processed flag was lost, then force a replay.
    PaymentWebhookEvent.objects.filter(pk=record.pk).update(processed=False)
    record.refresh_from_db()

    assert replay_failed_webhook(record) is True
    assert get_or_create_wallet(user).balance == Decimal("40.00")
    assert WalletLedgerEntry.objects.filter(wallet__user=user).count() == 1


# ---------------------------------------------------------------------------
# Cross-provider forgery (found in the pre-production audit)
# ---------------------------------------------------------------------------


def _live_payment(user, amount="500.00", provider="paystack"):
    return Payment.objects.create(
        user=user, reference=f"VGH-PAY-{provider.upper()[:4]}LIVE", provider=provider,
        amount=Decimal(amount), phone="+233241234567", network="MTN",
    )


def test_a_mock_signed_webhook_cannot_settle_a_live_provider_payment(user, api, settings):
    """The exploit: take a real deposit's reference, 'confirm' it with a webhook
    signed by the mock adapter's publicly known secret."""
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "paystack",
                         "WEBHOOK_PROVIDERS": []}
    payment = _live_payment(user)

    raw, headers = build_webhook(reference=payment.reference, amount="500.00")
    response = post_webhook(api, raw, headers)

    # The mock endpoint is not enabled, so it looks absent.
    assert response.status_code == 404
    assert get_or_create_wallet(user).balance == Decimal("0.00")
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_an_enabled_provider_still_cannot_settle_another_providers_payment(user, api, settings):
    """Defence in depth: even with both endpoints live (a switchover window), a
    callback only settles payments made with its own provider."""
    from apps.audit.models import SuspiciousActivity

    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "paystack",
                         "WEBHOOK_PROVIDERS": ["mock"]}
    payment = _live_payment(user)

    raw, headers = build_webhook(reference=payment.reference, amount="500.00")
    response = post_webhook(api, raw, headers)

    assert response.status_code == 200
    assert get_or_create_wallet(user).balance == Decimal("0.00")
    assert SuspiciousActivity.objects.filter(
        user=user, kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY, level="HIGH"
    ).exists()


def test_the_active_provider_webhook_still_works(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "30.00").data["reference"]
    raw, headers = build_webhook(reference=reference, amount="30.00")

    assert post_webhook(api, raw, headers).status_code == 200
    assert get_or_create_wallet(user).balance == Decimal("30.00")


# ---------------------------------------------------------------------------
# Over-payment
# ---------------------------------------------------------------------------


def test_a_large_overpayment_is_held_not_credited(user, auth, api):
    """A provider reporting 100x the amount is far likelier a bug than a gift."""
    client = auth(user)
    reference = start_deposit(client, "50.00").data["reference"]

    raw, headers = build_webhook(reference=reference, amount="5000.00")
    post_webhook(api, raw, headers)

    assert get_or_create_wallet(user).balance == Decimal("0.00")
    payment = Payment.objects.get(reference=reference)
    assert payment.credited_at is None
    assert "held for review" in payment.failure_reason


def test_a_small_overpayment_within_tolerance_is_credited(user, auth, api):
    client = auth(user)
    reference = start_deposit(client, "100.00").data["reference"]

    raw, headers = build_webhook(reference=reference, amount="102.00")
    post_webhook(api, raw, headers)

    assert get_or_create_wallet(user).balance == Decimal("102.00")


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_the_browsable_api_is_not_served_outside_debug(api):
    response = api.get("/api/v1/services/", HTTP_ACCEPT="text/html")
    assert "text/html" not in response.get("Content-Type", "")


def test_api_responses_carry_a_locked_down_csp(api):
    response = api.get("/api/v1/services/")
    assert response["Content-Security-Policy"].startswith("default-src 'none'")
    assert response["Cache-Control"] == "no-store, private"


def test_a_verified_but_unparseable_webhook_is_kept_for_a_human(api, user, monkeypatch):
    """Signed by the provider, not understood by us: it must not vanish."""
    from apps.common.errors import ProviderError
    from apps.payments.mock import MockPaymentProvider
    from apps.payments.services import UNPARSED_EVENT_TYPE

    def refuse(self, raw_body, headers):
        raise ProviderError("unknown event shape")

    monkeypatch.setattr(MockPaymentProvider, "parse_webhook", refuse)
    raw, headers = build_webhook(reference="VGH-PAY-WHATEVER", amount="10.00")

    assert post_webhook(api, raw, headers).status_code == 200

    stored = PaymentWebhookEvent.objects.get(event_type=UNPARSED_EVENT_TYPE)
    assert stored.signature_valid is True
    assert stored.processed is False  # counted by /admin/health as needing attention
    assert "unknown event shape" in stored.processing_error
    assert "VGH-PAY-WHATEVER" in stored.payload["raw"]
