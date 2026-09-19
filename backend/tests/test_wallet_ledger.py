"""Ledger integrity.

These are the tests that matter most. If any of them fail, the platform is
losing or inventing money.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.common.errors import InsufficientFunds, ValidationFailed
from apps.wallet.models import LedgerDirection, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, post_entry, verify_wallet_integrity

pytestmark = pytest.mark.django_db


def credit(wallet, amount, key):
    return post_entry(
        wallet=wallet,
        amount=Decimal(amount),
        entry_type=LedgerEntryType.DEPOSIT,
        direction=LedgerDirection.CREDIT,
        idempotency_key=key,
    )


def debit(wallet, amount, key):
    return post_entry(
        wallet=wallet,
        amount=Decimal(amount),
        entry_type=LedgerEntryType.PURCHASE,
        direction=LedgerDirection.DEBIT,
        idempotency_key=key,
    )


def test_wallet_is_created_with_the_user(user):
    assert user.wallet is not None
    assert user.wallet.balance == Decimal("0.00")
    assert user.wallet.currency == "GHS"


def test_credit_moves_balance_and_records_before_and_after(user):
    wallet = get_or_create_wallet(user)
    entry = credit(wallet, "50.00", "k1")
    wallet.refresh_from_db()

    assert wallet.balance == Decimal("50.00")
    assert entry.balance_before == Decimal("0.00")
    assert entry.balance_after == Decimal("50.00")
    assert entry.signed_amount == Decimal("50.00")


def test_same_idempotency_key_credits_only_once(user):
    """The single most important guarantee in the system."""
    wallet = get_or_create_wallet(user)

    entries = [credit(wallet, "50.00", "same-key") for _ in range(5)]
    wallet.refresh_from_db()

    assert wallet.balance == Decimal("50.00")
    assert len({entry.id for entry in entries}) == 1
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1


def test_debit_beyond_balance_is_refused_and_writes_nothing(user):
    wallet = get_or_create_wallet(user)
    credit(wallet, "10.00", "k1")

    with pytest.raises(InsufficientFunds) as exc:
        debit(wallet, "10.01", "k2")

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("10.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1
    assert exc.value.details["shortfall"] == "0.01"


def test_entry_type_cannot_move_the_wrong_way(user):
    wallet = get_or_create_wallet(user)
    with pytest.raises(ValidationFailed):
        post_entry(
            wallet=wallet,
            amount=Decimal("5.00"),
            entry_type=LedgerEntryType.PURCHASE,
            direction=LedgerDirection.CREDIT,  # a purchase can never be a credit
            idempotency_key="wrong-way",
        )


def test_zero_and_negative_amounts_are_refused(user):
    wallet = get_or_create_wallet(user)
    for amount in ("0.00", "-5.00"):
        with pytest.raises(ValidationFailed):
            credit(wallet, amount, f"bad-{amount}")


def test_totals_track_deposits_and_spend(user):
    wallet = get_or_create_wallet(user)
    credit(wallet, "100.00", "d1")
    debit(wallet, "30.00", "p1")
    wallet.refresh_from_db()

    assert wallet.balance == Decimal("70.00")
    assert wallet.total_deposited == Decimal("100.00")
    assert wallet.total_spent == Decimal("30.00")


def test_ledger_chain_is_continuous(user):
    wallet = get_or_create_wallet(user)
    credit(wallet, "100.00", "d1")
    debit(wallet, "25.00", "p1")
    debit(wallet, "25.00", "p2")
    credit(wallet, "10.00", "d2")

    report = verify_wallet_integrity(get_or_create_wallet(user))
    assert report["ok"] is True
    assert report["drift"] == "0.00"
    assert report["chain_breaks"] == []
    assert report["derived_balance"] == "60.00"


def test_integrity_check_detects_a_tampered_balance(user):
    from apps.wallet.models import Wallet

    wallet = get_or_create_wallet(user)
    credit(wallet, "100.00", "d1")

    # Simulate someone bypassing the ledger service entirely.
    Wallet.objects.filter(pk=wallet.pk).update(balance=Decimal("999.00"))

    report = verify_wallet_integrity(Wallet.objects.get(pk=wallet.pk))
    assert report["ok"] is False
    assert report["drift"] == "899.00"


def test_ledger_entries_are_immutable(user):
    wallet = get_or_create_wallet(user)
    entry = credit(wallet, "20.00", "d1")

    entry.amount = Decimal("2000.00")
    with pytest.raises(ValueError, match="immutable"):
        entry.save()


def test_frozen_wallet_blocks_spending_but_not_deposits(user):
    from apps.wallet.models import Wallet
    from apps.wallet.services import WalletFrozen

    wallet = get_or_create_wallet(user)
    credit(wallet, "100.00", "d1")
    Wallet.objects.filter(pk=wallet.pk).update(is_frozen=True)
    wallet.refresh_from_db()

    with pytest.raises(WalletFrozen):
        debit(wallet, "10.00", "p1")

    # A deposit into a frozen wallet still lands - we hold the money rather
    # than bouncing it back to the user's MoMo account.
    post_entry(
        wallet=wallet,
        amount=Decimal("10.00"),
        entry_type=LedgerEntryType.DEPOSIT,
        direction=LedgerDirection.CREDIT,
        idempotency_key="d2",
        allow_frozen=True,
    )
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("110.00")
