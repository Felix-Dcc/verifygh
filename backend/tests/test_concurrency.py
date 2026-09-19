"""Concurrency: the same balance must never be spent twice.

These tests run real threads against real database connections. On PostgreSQL
the wallet row lock serialises them; on SQLite the compare-and-set plus the
database write lock does. Either way the invariant is the same, so the test is
written against the invariant rather than the mechanism.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import connections

from apps.common.errors import APIError
from apps.wallet.models import LedgerDirection, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, post_entry, verify_wallet_integrity

pytestmark = pytest.mark.django_db(transaction=True)


def _spend(wallet_id, amount: str, key: str, results: list, index: int):
    """Run one debit on its own connection, like a separate request would."""
    from apps.wallet.models import Wallet

    try:
        wallet = Wallet.objects.get(pk=wallet_id)
        entry = post_entry(
            wallet=wallet,
            amount=Decimal(amount),
            entry_type=LedgerEntryType.PURCHASE,
            direction=LedgerDirection.DEBIT,
            idempotency_key=key,
        )
        results[index] = ("ok", entry.reference)
    except APIError as exc:
        results[index] = ("refused", exc.code)
    except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
        results[index] = ("error", repr(exc))
    finally:
        connections.close_all()


def test_two_concurrent_purchases_cannot_overspend(user, funded_wallet):
    """GHS 20 balance, two simultaneous GHS 15 purchases: exactly one succeeds."""
    wallet = funded_wallet(user, "20.00")

    results: list = [None, None]
    threads = [
        threading.Thread(target=_spend, args=(wallet.pk, "15.00", f"spend-{index}", results,
                                              index))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    outcomes = [result[0] for result in results]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("refused") == 1, results
    assert results[outcomes.index("refused")][1] == "INSUFFICIENT_FUNDS"

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("5.00")
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.PURCHASE
    ).count() == 1


def test_many_concurrent_purchases_stop_exactly_at_the_balance(user, funded_wallet):
    """GHS 50 balance, ten simultaneous GHS 10 purchases: exactly five succeed."""
    wallet = funded_wallet(user, "50.00")

    attempts = 10
    results: list = [None] * attempts
    threads = [
        threading.Thread(
            target=_spend, args=(wallet.pk, "10.00", f"burst-{index}", results, index)
        )
        for index in range(attempts)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    succeeded = [result for result in results if result and result[0] == "ok"]
    errored = [result for result in results if result and result[0] == "error"]

    assert not errored, errored
    assert len(succeeded) == 5, results

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")

    report = verify_wallet_integrity(wallet)
    assert report["ok"] is True, report


def test_concurrent_identical_idempotency_keys_credit_once(user):
    """Five webhook deliveries landing at once still credit a wallet once."""
    wallet = get_or_create_wallet(user)

    def _credit(index: int, results: list):
        from apps.wallet.models import Wallet

        try:
            target = Wallet.objects.get(pk=wallet.pk)
            entry = post_entry(
                wallet=target,
                amount=Decimal("100.00"),
                entry_type=LedgerEntryType.DEPOSIT,
                direction=LedgerDirection.CREDIT,
                idempotency_key="deposit:VGH-PAY-SAME",
            )
            results[index] = entry.reference
        finally:
            connections.close_all()

    results: list = [None] * 5
    threads = [threading.Thread(target=_credit, args=(index, results)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("100.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1
    assert len({reference for reference in results if reference}) == 1
