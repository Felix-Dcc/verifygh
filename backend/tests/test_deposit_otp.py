"""The Mobile Money OTP step.

The bug this suite exists to prevent, in full:

Paystack's charge response can come back as `send_otp` - it has texted the
customer a code and will sit there until we POST it back - or `pay_offline`,
where the handset is prompted and we simply wait. Both were mapped to
PROCESSING, so both rendered "approve on your phone, waiting for confirmation".
A customer in the `send_otp` branch received a code, had nowhere to enter it,
and watched the charge expire. Nothing errored; the money simply never arrived.

So the tests below care about two things above all: that the two states stay
distinguishable, and that submitting a code - however successful the response
looks - never by itself credits a wallet.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.common.errors import (
    InvalidStateTransition,
    LimitExceeded,
    NotFound,
    ProviderError,
    ValidationFailed,
)
from apps.payments.base import ChargeDTO, ChargeStatus
from apps.payments.models import Payment, PaymentStatus
from apps.payments.paystack import STATUS_MAP, UNSUPPORTED_ACTIONS, PaystackProvider
from apps.payments.services import MAX_OTP_ATTEMPTS, submit_deposit_otp
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
OTP_URL = "/api/v1/payments/{ref}/otp/"


# ---------------------------------------------------------------------------
# The mapping itself - where the bug lived
# ---------------------------------------------------------------------------


def test_send_otp_and_pay_offline_are_not_the_same_state():
    """They are opposites: one needs the customer to type, one needs them to
    wait. Collapsing them is the whole bug."""
    assert STATUS_MAP["send_otp"] is ChargeStatus.OTP_REQUIRED
    assert STATUS_MAP["pay_offline"] is ChargeStatus.PHONE_AUTH_REQUIRED
    assert STATUS_MAP["send_otp"] is not STATUS_MAP["pay_offline"]


def test_no_documented_action_state_is_mapped_to_plain_processing():
    """PROCESSING means "nothing for anyone to do but wait"."""
    for raw in ("send_otp", "pay_offline"):
        assert STATUS_MAP[raw] is not ChargeStatus.PROCESSING


def test_success_is_only_ever_reached_from_the_provider_saying_success():
    successes = [raw for raw, mapped in STATUS_MAP.items() if mapped is ChargeStatus.SUCCESS]
    assert successes == ["success"]


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.content = b"x"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        path = url.split("paystack.co", 1)[-1]
        self.calls.append((method, path, kwargs.get("json") or {}))
        answer = self.answers.get(path)
        if answer is None:
            raise AssertionError(f"unrouted path: {path}")
        return answer


@pytest.fixture
def provider(settings):
    settings.PAYMENT_CREDENTIALS = {
        **settings.PAYMENT_CREDENTIALS,
        "paystack": {"secret_key": "sk_test_x", "public_key": "",
                     "base_url": "https://api.paystack.co"},
    }
    return PaystackProvider()


def wire(provider, answers):
    session = FakeSession(answers)
    provider._session = session
    return session


def test_a_charge_that_wants_an_otp_says_so(provider):
    wire(provider, {"/charge": FakeResponse(200, {
        "status": True, "data": {
            "reference": "ref-1", "status": "send_otp",
            "display_text": "Please enter the one-time password sent to your phone",
        }})})

    charge = provider.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network="MTN", reference="ref-1", email="a@b.com",
    )

    assert charge.status is ChargeStatus.OTP_REQUIRED
    # The provider's own wording, because it matches the SMS they just got.
    assert "one-time password" in charge.instructions


def test_a_charge_that_wants_a_handset_approval_says_so(provider):
    wire(provider, {"/charge": FakeResponse(200, {
        "status": True, "data": {
            "reference": "ref-2", "status": "pay_offline",
            "display_text": "Please complete authorization process on your mobile phone",
        }})})

    charge = provider.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network="MTN", reference="ref-2", email="a@b.com",
    )

    assert charge.status is ChargeStatus.PHONE_AUTH_REQUIRED


def test_submitting_an_otp_uses_the_documented_endpoint(provider):
    session = wire(provider, {"/charge/submit_otp": FakeResponse(200, {
        "status": True, "data": {"reference": "ref-3", "status": "pay_offline",
                                 "display_text": "Approve on your phone"}})})

    charge = provider.submit_otp(reference="ref-3", otp="123456")

    method, path, body = session.calls[0]
    assert (method, path) == ("POST", "/charge/submit_otp")
    assert body == {"otp": "123456", "reference": "ref-3"}
    # Submitting a code does not mean paid - here it moved to handset approval.
    assert charge.status is ChargeStatus.PHONE_AUTH_REQUIRED


def test_an_unsupported_authorization_step_fails_rather_than_hanging(provider):
    """send_pin and friends are card flows. We cannot drive them, so the
    customer must be told now, not after the window closes."""
    assert "send_pin" in UNSUPPORTED_ACTIONS
    wire(provider, {"/charge": FakeResponse(200, {
        "status": True, "data": {"reference": "ref-4", "status": "send_pin"}})})

    charge = provider.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network="MTN", reference="ref-4", email="a@b.com",
    )

    assert charge.status is ChargeStatus.FAILED


def test_an_unknown_provider_status_is_never_success(provider):
    wire(provider, {"/charge": FakeResponse(200, {
        "status": True, "data": {"reference": "ref-5", "status": "something_new"}})})

    charge = provider.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network="MTN", reference="ref-5", email="a@b.com",
    )

    assert charge.status is ChargeStatus.PENDING


def test_a_provider_with_no_otp_flow_refuses_a_code():
    """So a code cannot be handed to a provider that never asked for one."""
    from apps.payments.mock import MockPaymentProvider

    with pytest.raises(ProviderError):
        MockPaymentProvider().submit_otp(reference="x", otp="123456")


# ---------------------------------------------------------------------------
# The service - ownership, state, expiry, attempts
# ---------------------------------------------------------------------------


@pytest.fixture
def buyer(db):
    account = User.objects.create_user(
        email="otp-payer@example.com", password=PASSWORD, phone="+233241234500"
    )
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


@pytest.fixture
def awaiting_otp(buyer):
    from django.utils import timezone
    from datetime import timedelta

    return Payment.objects.create(
        user=buyer, reference="VGH-PAY-OTP00001", provider="paystack",
        provider_reference="VGH-PAY-OTP00001", amount=Decimal("10.00"), currency="GHS",
        phone="+233241234500", network="MTN", status=PaymentStatus.OTP_REQUIRED,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def stub_provider(monkeypatch, result):
    """Make the registry hand back a provider whose submit_otp is scripted."""
    from apps.payments import services as payment_services

    class Stub:
        key = "paystack"
        calls: list = []

        def submit_otp(self, *, reference, otp):
            Stub.calls.append((reference, otp))
            if isinstance(result, Exception):
                raise result
            return result

    stub = Stub()
    monkeypatch.setattr(payment_services, "get_payment_provider", lambda *a, **k: stub)
    return Stub


def test_a_valid_code_moves_the_payment_on(buyer, awaiting_otp, monkeypatch):
    stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference,
        status=ChargeStatus.PHONE_AUTH_REQUIRED,
        instructions="Approve on your phone",
    ))

    payment = submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="123456")

    assert payment.status == PaymentStatus.PHONE_AUTH
    assert payment.instructions == "Approve on your phone"


def test_submitting_a_code_never_credits_a_wallet(buyer, awaiting_otp, monkeypatch):
    """Even when the provider's reply to the OTP says success.

    Money moves only from a verified callback or our own outbound verification.
    A response to something the customer did in a browser is not proof.
    """
    stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference, status=ChargeStatus.SUCCESS,
    ))
    wallet = get_or_create_wallet(buyer)
    before = wallet.balance

    submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="123456")

    wallet.refresh_from_db()
    assert wallet.balance == before, "an OTP response credited the wallet"
    awaiting_otp.refresh_from_db()
    assert awaiting_otp.credited_at is None
    assert awaiting_otp.ledger_entry_id is None


def test_another_users_payment_is_not_reachable(buyer, awaiting_otp, db):
    stranger = User.objects.create_user(email="stranger@example.com", password=PASSWORD)

    with pytest.raises(NotFound):
        submit_deposit_otp(user=stranger, reference=awaiting_otp.reference, otp="123456")


def test_a_payment_that_is_not_awaiting_a_code_refuses_one(buyer, awaiting_otp, monkeypatch):
    Payment.objects.filter(pk=awaiting_otp.pk).update(status=PaymentStatus.PHONE_AUTH)

    with pytest.raises(InvalidStateTransition) as raised:
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="123456")
    assert raised.value.code == "OTP_NOT_EXPECTED"


def test_an_already_successful_payment_returns_quietly(buyer, awaiting_otp):
    """A double-tap on Confirm must not look like a failure."""
    Payment.objects.filter(pk=awaiting_otp.pk).update(status=PaymentStatus.SUCCESS)

    payment = submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="123456")

    assert payment.status == PaymentStatus.SUCCESS


def test_an_expired_payment_is_settled_not_submitted(buyer, awaiting_otp, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    Payment.objects.filter(pk=awaiting_otp.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    Stub = stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference, status=ChargeStatus.SUCCESS))

    with pytest.raises(InvalidStateTransition) as raised:
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="123456")

    assert raised.value.code == "PAYMENT_EXPIRED"
    assert Stub.calls == [], "an expired payment was still sent upstream"
    awaiting_otp.refresh_from_db()
    assert awaiting_otp.status == PaymentStatus.EXPIRED


@pytest.mark.parametrize("bad", ["", "12", "abcdef", "1234567890123"])
def test_a_malformed_code_never_reaches_the_provider(buyer, awaiting_otp, monkeypatch, bad):
    Stub = stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference, status=ChargeStatus.SUCCESS))

    with pytest.raises(ValidationFailed):
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp=bad)

    assert Stub.calls == []


def test_spaces_and_dashes_are_tolerated(buyer, awaiting_otp, monkeypatch):
    """People paste codes straight out of a message."""
    Stub = stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference,
        status=ChargeStatus.PHONE_AUTH_REQUIRED))

    submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp=" 123-456 ")

    assert Stub.calls[0][1] == "123456"


def test_attempts_are_capped(buyer, awaiting_otp, monkeypatch):
    """A six-digit code behind a guessable reference must not be an oracle."""
    stub_provider(monkeypatch, ProviderError("rejected"))

    for _ in range(MAX_OTP_ATTEMPTS):
        with pytest.raises(ValidationFailed):
            submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="000000")

    with pytest.raises(LimitExceeded) as raised:
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="000000")
    assert raised.value.code == "OTP_ATTEMPTS_EXCEEDED"


def test_a_rejected_code_says_how_many_tries_remain(buyer, awaiting_otp, monkeypatch):
    stub_provider(monkeypatch, ProviderError("rejected"))

    with pytest.raises(ValidationFailed) as raised:
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="000000")

    assert raised.value.details["attempts_remaining"] == MAX_OTP_ATTEMPTS - 1


def test_a_failed_submission_still_consumes_an_attempt(buyer, awaiting_otp, monkeypatch):
    """Otherwise hanging up mid-request would reset the counter forever."""
    stub_provider(monkeypatch, ProviderError("boom"))

    with pytest.raises(ValidationFailed):
        submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="000000")

    awaiting_otp.refresh_from_db()
    assert awaiting_otp.otp_attempts == 1


def test_the_code_is_never_stored_on_the_payment(buyer, awaiting_otp, monkeypatch):
    stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference,
        status=ChargeStatus.PHONE_AUTH_REQUIRED))

    submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="987654")

    awaiting_otp.refresh_from_db()
    blob = " ".join(str(v) for v in (
        awaiting_otp.instructions, awaiting_otp.failure_reason,
        awaiting_otp.metadata, awaiting_otp.provider_reference,
    ))
    assert "987654" not in blob


def test_the_code_is_never_logged(buyer, awaiting_otp, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="verifygh")
    stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference,
        status=ChargeStatus.PHONE_AUTH_REQUIRED))

    submit_deposit_otp(user=buyer, reference=awaiting_otp.reference, otp="424242")

    for record in caplog.records:
        assert "424242" not in record.getMessage()
        assert "424242" not in str(record.__dict__)


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_the_endpoint_requires_authentication(api, awaiting_otp):
    response = api.post(OTP_URL.format(ref=awaiting_otp.reference), {"otp": "123456"},
                        format="json")

    assert response.status_code in (401, 403)


def test_the_endpoint_submits_and_returns_the_new_state(api, auth, buyer, awaiting_otp,
                                                        monkeypatch):
    stub_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference,
        status=ChargeStatus.PHONE_AUTH_REQUIRED,
        instructions="Approve on your phone"))

    response = auth(buyer, PASSWORD).post(
        OTP_URL.format(ref=awaiting_otp.reference), {"otp": "123456"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["status"] == "PHONE_AUTH"
    # The code must not come back out.
    assert "otp" not in response.data


def test_one_user_cannot_submit_a_code_for_another(api, auth, awaiting_otp, db):
    stranger = User.objects.create_user(email="stranger2@example.com", password=PASSWORD)

    response = auth(stranger, PASSWORD).post(
        OTP_URL.format(ref=awaiting_otp.reference), {"otp": "123456"}, format="json"
    )

    assert response.status_code == 404


def test_the_frontend_cannot_mark_a_payment_successful(api, auth, buyer, awaiting_otp):
    """There is no endpoint for it, and PATCHing the payment must not work."""
    client = auth(buyer, PASSWORD)

    response = client.patch(
        f"/api/v1/payments/{awaiting_otp.reference}/",
        {"status": "SUCCESS", "amount": "9999.00"}, format="json",
    )

    assert response.status_code in (403, 404, 405)
    awaiting_otp.refresh_from_db()
    assert awaiting_otp.status == PaymentStatus.OTP_REQUIRED
    assert awaiting_otp.amount == Decimal("10.00")
