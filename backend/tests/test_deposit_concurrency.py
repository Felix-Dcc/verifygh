"""Racing the parts of a deposit a customer can trigger twice.

A phone on a slow network sends the same tap twice. A customer with two tabs
open presses "Check again" in both. These run real threads on real
connections; on PostgreSQL the payment row lock decides between them, and the
assertions are on the money, so the result is proven either way.

Duplicate webhooks are covered in test_concurrency_flows.py.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import connections
from django.utils import timezone

from apps.payments.base import ChargeDTO, ChargeStatus
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import MAX_OTP_ATTEMPTS, submit_deposit_otp
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db(transaction=True)

PASSWORD = "Correct-Horse-Battery-1"


def run_concurrently(target, count: int) -> list:
    """Start `count` threads behind a barrier so they genuinely overlap."""
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def _worker(index: int):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
            results[index] = ("error", repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.fixture
def payer(db):
    from apps.accounts.models import User

    account = User.objects.create_user(email="racer@example.com", password=PASSWORD,
                                       phone="+233201234567")
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


@pytest.fixture
def awaiting_otp(payer):
    return Payment.objects.create(
        user=payer, reference="VGH-PAY-RACE0001", provider="paystack",
        provider_reference="VGH-PAY-RACE0001", amount=Decimal("10.00"), currency="GHS",
        phone="+233201234567", network="TELECEL", status=PaymentStatus.OTP_REQUIRED,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def scripted_provider(monkeypatch, result):
    """A provider whose submit_otp answers `result` and counts its calls."""
    from apps.payments import services as payment_services

    calls = []
    lock = threading.Lock()

    class Stub:
        key = "paystack"

        def submit_otp(self, *, reference, otp):
            with lock:
                calls.append(otp)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(payment_services, "get_payment_provider", lambda *a, **k: Stub())
    return calls


def test_simultaneous_otp_submissions_never_exceed_the_attempt_cap(payer, awaiting_otp,
                                                                   monkeypatch):
    """The cap is only a cap if two requests cannot both read "2 attempts used"
    and both proceed. The row lock is what makes the count honest."""
    from apps.common.errors import ProviderError

    calls = scripted_provider(monkeypatch, ProviderError("rejected"))

    run_concurrently(
        lambda _i: submit_deposit_otp(user=payer, reference=awaiting_otp.reference,
                                      otp="000000"),
        10,
    )

    awaiting_otp.refresh_from_db()
    assert len(calls) <= MAX_OTP_ATTEMPTS, (
        f"{len(calls)} codes reached the provider; the cap is {MAX_OTP_ATTEMPTS}"
    )
    assert awaiting_otp.otp_attempts <= MAX_OTP_ATTEMPTS


def test_a_double_tapped_code_never_credits_the_wallet(payer, awaiting_otp, monkeypatch):
    """Even with Paystack answering success to both, the OTP path moves no money.
    Only verified confirmation does - and it is idempotent."""
    scripted_provider(monkeypatch, ChargeDTO(
        provider_reference=awaiting_otp.reference, status=ChargeStatus.SUCCESS))

    # The verification call the success path makes. Answering FAILED proves the
    # OTP response alone was never trusted to credit anything.
    from apps.payments import services as payment_services

    monkeypatch.setattr(payment_services, "reconcile_payment", lambda payment: payment)

    run_concurrently(
        lambda _i: submit_deposit_otp(user=payer, reference=awaiting_otp.reference,
                                      otp="123456"),
        6,
    )

    wallet = get_or_create_wallet(payer)
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00"), "an OTP response credited the wallet"
    assert wallet.ledger_entries.count() == 0


def verifying_provider(monkeypatch, status, amount):
    """A provider whose verify endpoint answers `status` for `amount`, counting calls.

    Stubbed rather than driving the mock adapter, which only recognises charges
    it initiated itself - an earlier version of these tests created payments
    directly, had every verification raise "unknown reference", and so passed
    the failed-payment case for the wrong reason: nothing was credited because
    nothing was ever checked.
    """
    from apps.payments import services as payment_services

    calls = []
    lock = threading.Lock()

    class Stub:
        key = "paystack"

        def fetch_charge(self, reference):
            with lock:
                calls.append(reference)
            return ChargeDTO(provider_reference=reference, status=status,
                             amount=amount, currency="GHS")

    monkeypatch.setattr(payment_services, "get_payment_provider", lambda *a, **k: Stub())
    return calls


def _awaiting_phone(payer, reference):
    return Payment.objects.create(
        user=payer, reference=reference, provider="paystack",
        provider_reference=reference, amount=Decimal("25.00"), currency="GHS",
        phone="+233201234567", network="TELECEL", status=PaymentStatus.PHONE_AUTH,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def test_simultaneous_status_checks_credit_a_confirmed_payment_once(payer, monkeypatch):
    """Two tabs, both pressing "Check again" on a payment Paystack has
    confirmed. Each asks the provider; only one may credit."""
    from apps.payments.services import reconcile_payment

    calls = verifying_provider(monkeypatch, ChargeStatus.SUCCESS, Decimal("25.00"))
    payment = _awaiting_phone(payer, "VGH-PAY-RACE0002")

    run_concurrently(lambda _i: reconcile_payment(Payment.objects.get(pk=payment.pk)), 8)

    assert calls, "no verification was ever made - this test would prove nothing"
    wallet = get_or_create_wallet(payer)
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("25.00"), f"credited {wallet.balance}, not 25.00"
    assert wallet.ledger_entries.count() == 1
    assert verify_wallet_integrity(wallet)["ok"] is True

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.credited_at is not None


def test_status_checks_racing_a_failed_payment_credit_nothing(payer, monkeypatch):
    from apps.payments.services import reconcile_payment

    calls = verifying_provider(monkeypatch, ChargeStatus.FAILED, Decimal("25.00"))
    payment = _awaiting_phone(payer, "VGH-PAY-RACE0003")

    run_concurrently(lambda _i: reconcile_payment(Payment.objects.get(pk=payment.pk)), 8)

    # The guard against a vacuous pass: the provider really was asked, and
    # really did say failed.
    assert calls, "no verification was ever made - this test would prove nothing"
    wallet = get_or_create_wallet(payer)
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")
    assert wallet.ledger_entries.count() == 0
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED


def test_an_amount_mismatch_on_verification_never_credits_the_charged_figure(payer,
                                                                             monkeypatch):
    """Paystack reports a different amount from the one we asked for."""
    from apps.payments.services import reconcile_payment

    verifying_provider(monkeypatch, ChargeStatus.SUCCESS, Decimal("2500.00"))
    payment = _awaiting_phone(payer, "VGH-PAY-RACE0004")

    run_concurrently(lambda _i: reconcile_payment(Payment.objects.get(pk=payment.pk)), 4)

    wallet = get_or_create_wallet(payer)
    wallet.refresh_from_db()
    assert wallet.balance != Decimal("2500.00"), "credited the provider's figure unchecked"
    assert wallet.ledger_entries.count() <= 1
