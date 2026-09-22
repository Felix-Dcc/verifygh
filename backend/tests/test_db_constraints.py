"""Constraints the database enforces on every backend, whoever the writer is.

Each test goes around the service layer on purpose - that is the scenario the
constraints exist for: a management shell, a data migration, a future bug.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone

from apps.payments.models import Payment
from apps.wallet.models import Wallet, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db


def refused(fn):
    """The database refuses the write.

    Either error counts: PostgreSQL rejects an over-long enum value with
    DataError before the CHECK constraint is reached, while SQLite has no
    length enforcement and fails the CHECK. Both mean "the database said no".
    """
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        fn()


def _entry(wallet, **overrides):
    fields = {"wallet": wallet, "reference": "VGH-LED-CHECK001", "sequence": 1,
              "idempotency_key": "k", "entry_type": "DEPOSIT", "direction": "CREDIT",
              "amount": Decimal("5.00"), "balance_before": Decimal("0.00"),
              "balance_after": Decimal("5.00"), "currency": "GHS"}
    fields.update(overrides)
    return WalletLedgerEntry.objects.create(**fields)


def test_a_wallet_balance_can_never_go_negative(user):
    wallet = get_or_create_wallet(user)
    refused(lambda: Wallet.objects.filter(pk=wallet.pk).update(balance=Decimal("-0.01")))


def test_wallet_running_totals_can_never_go_negative(user):
    wallet = get_or_create_wallet(user)
    refused(lambda: Wallet.objects.filter(pk=wallet.pk).update(total_spent=Decimal("-1.00")))
    refused(lambda: Wallet.objects.filter(pk=wallet.pk).update(total_deposited=Decimal("-1")))


@pytest.mark.parametrize(("entry_type", "direction"), [
    ("DEPOSIT", "DEBIT"), ("REFUND", "DEBIT"), ("PURCHASE", "CREDIT"),
    ("WITHDRAWAL", "CREDIT"), ("BOGUS", "CREDIT"), ("ADJUSTMENT", "SIDEWAYS"),
])
def test_a_ledger_direction_must_fit_its_type(user, entry_type, direction):
    wallet = get_or_create_wallet(user)
    refused(lambda: _entry(wallet, entry_type=entry_type, direction=direction))


def test_ledger_amounts_are_positive_and_sequences_start_at_one(user):
    wallet = get_or_create_wallet(user)
    refused(lambda: _entry(wallet, amount=Decimal("0.00")))
    refused(lambda: _entry(wallet, sequence=0))


def test_a_ledger_key_and_sequence_are_unique_per_wallet(user):
    wallet = get_or_create_wallet(user)
    _entry(wallet)
    refused(lambda: _entry(wallet, reference="VGH-LED-CHECK002", sequence=2))
    refused(lambda: _entry(wallet, reference="VGH-LED-CHECK003", idempotency_key="k2"))


def _payment(user, **overrides):
    fields = {"user": user, "reference": "VGH-PAY-CHECK001", "provider": "mock",
              "amount": Decimal("10.00"), "phone": "+233241234567", "network": "MTN"}
    fields.update(overrides)
    return Payment.objects.create(**fields)


def test_only_a_successful_payment_can_be_marked_credited(user):
    payment = _payment(user)
    refused(lambda: Payment.objects.filter(pk=payment.pk).update(credited_at=timezone.now()))
    Payment.objects.filter(pk=payment.pk).update(status="SUCCESS", credited_at=timezone.now())
    refused(lambda: Payment.objects.filter(pk=payment.pk).update(status="FAILED"))


def test_payment_status_and_amount_are_constrained(user):
    refused(lambda: _payment(user, status="PAID_BY_CLIENT"))
    refused(lambda: _payment(user, amount=Decimal("0.00")))


def test_order_status_and_refund_amount_are_constrained(user, catalog, funded_wallet):
    from apps.orders.models import Order, Refund
    from apps.orders.services import create_order

    funded_wallet(user, "100.00")
    order = create_order(user=user, service_slug="instagram", country_code="US",
                         idempotency_key="constraints")
    refused(lambda: Order.objects.filter(pk=order.pk).update(status="SHIPPED"))
    refused(lambda: Refund.objects.create(order=order, reference="VGH-REF-CHECK001",
                                          amount=Decimal("0.00"), reason="ADMIN_GOODWILL"))
