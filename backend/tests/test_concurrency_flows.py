"""Concurrency across the full money flows, not just the ledger primitive.

`test_concurrency.py` proves `post_entry` cannot overspend. These tests go one
level up - `create_order`, `issue_refund`, `process_webhook` - because a flow
can be unsafe even when its primitive is safe (an order row written outside
the debit's transaction, a refund keyed on something non-unique, ...).

Real threads, real connections. On SQLite the database write lock serialises
them; on PostgreSQL (CI) the row locks do. The assertions are on invariants,
so the same test proves both.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import IntegrityError, connections, transaction

from apps.common.errors import APIError
from apps.orders.models import Order, OrderStatus, Refund
from apps.payments import mock as payment_mock
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import process_webhook
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(target, count: int) -> list:
    """Start `count` threads behind a barrier so they really do overlap."""
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def _worker(index: int):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except APIError as exc:
            results[index] = ("refused", exc.code)
        except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
            results[index] = ("error", repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def fresh(model, pk):
    return model.objects.get(pk=pk)


def buy(user_pk, key: str):
    from apps.accounts.models import User
    from apps.orders.services import create_order

    order = create_order(user=fresh(User, user_pk), service_slug="instagram",
                         country_code="US", idempotency_key=key)
    return order.pk


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------


def test_two_simultaneous_orders_cannot_double_spend(user, catalog, funded_wallet):
    price = _price()
    wallet = funded_wallet(user, str(price + Decimal("0.50")))  # enough for one

    results = run_concurrently(lambda index: buy(user.pk, f"race-{index}"), 2)

    outcomes = sorted(result[0] for result in results)
    assert outcomes == ["ok", "refused"], results
    assert [r for r in results if r[0] == "refused"][0][1] == "INSUFFICIENT_FUNDS"

    # The refused purchase left nothing behind - no orphan order, no debit.
    assert Order.objects.filter(user=user).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.PURCHASE).count() == 1
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.50")
    assert verify_wallet_integrity(wallet)["ok"]


def test_a_double_clicked_purchase_buys_once(user, catalog, funded_wallet):
    """Same idempotency key from two requests at once: one order, one debit."""
    wallet = funded_wallet(user, "200.00")

    results = run_concurrently(lambda index: buy(user.pk, "double-click"), 4)

    assert all(result[0] == "ok" for result in results), results
    assert len({result[1] for result in results}) == 1
    assert Order.objects.filter(user=user).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.PURCHASE).count() == 1
    wallet.refresh_from_db()
    assert verify_wallet_integrity(wallet)["ok"]


def test_many_simultaneous_orders_stop_exactly_at_the_balance(user, catalog, funded_wallet,
                                                              settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_ACTIVE_ORDERS": 50}
    price = _price()
    wallet = funded_wallet(user, str(price * 3))

    results = run_concurrently(lambda index: buy(user.pk, f"burst-{index}"), 6)

    assert sum(1 for result in results if result[0] == "ok") == 3, results
    assert all(result[0] != "error" for result in results), results
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")
    assert Order.objects.filter(user=user).count() == 3
    assert verify_wallet_integrity(wallet)["ok"]


def test_a_failure_after_the_debit_rolls_the_whole_purchase_back(
    user, catalog, funded_wallet, monkeypatch
):
    """If anything inside the purchase transaction fails after the money has
    moved, the debit and the order disappear together."""
    from apps.orders import services as order_services

    wallet = funded_wallet(user, "200.00")

    def explode(*args, **kwargs):
        raise RuntimeError("simulated crash after debit")

    monkeypatch.setattr(order_services.OrderEvent.objects, "create", explode)

    with pytest.raises(RuntimeError):
        buy(user.pk, "crash")

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert not Order.objects.filter(user=user).exists()
    assert not WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.PURCHASE).exists()


def test_a_provider_failure_refunds_in_full(user, catalog, funded_wallet):
    """The provider is called outside the money transaction; when it fails,
    the refund is its own ledger entry and the balance comes back whole."""
    from apps.orders.services import fulfil_order
    from apps.verification import mock as verification_mock

    wallet = funded_wallet(user, "200.00")
    order = fresh(Order, buy(user.pk, "provider-down"))
    verification_mock.force_scenario("PROVIDER_ERR")
    try:
        fulfil_order(order)
    finally:
        verification_mock.force_scenario(None)

    order.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status in (OrderStatus.FAILED, OrderStatus.REFUNDED)
    assert wallet.balance == Decimal("200.00")
    assert Refund.objects.filter(order=order).count() == 1
    assert verify_wallet_integrity(wallet)["ok"]


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


def test_simultaneous_refunds_of_one_order_credit_once(user, catalog, funded_wallet):
    from apps.orders.services import issue_refund

    wallet = funded_wallet(user, "200.00")
    order = fresh(Order, buy(user.pk, "refund-race"))
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.FAILED)

    def refund(index):
        issue_refund(fresh(Order, order.pk), reason="PROVIDER_FAILED")
        return index

    results = run_concurrently(refund, 5)

    assert all(result[0] == "ok" for result in results), results
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert Refund.objects.filter(order=order).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.REFUND).count() == 1
    assert verify_wallet_integrity(wallet)["ok"]


# ---------------------------------------------------------------------------
# Deposits and webhooks
# ---------------------------------------------------------------------------


def _payment(user, reference: str, amount: str = "25.00") -> Payment:
    return Payment.objects.create(
        user=user, reference=reference, provider="mock", amount=Decimal(amount),
        phone="+233241234567", network="MTN",
    )


def _deliver(raw: bytes, headers: dict):
    lowered = {key.lower(): value for key, value in headers.items()}
    return process_webhook(provider_key="mock", raw_body=raw, headers=lowered).status


def test_simultaneous_duplicate_webhooks_credit_once(user):
    payment = _payment(user, "VGH-PAY-DUPRACE1", "40.00")
    raw, headers = payment_mock.build_webhook(reference=payment.reference, amount="40.00",
                                              event_id="evt_same_delivery")

    results = run_concurrently(lambda index: _deliver(raw, headers), 5)

    assert all(result[0] == "ok" for result in results), results
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("40.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1


def test_different_events_for_one_payment_arriving_together_credit_once(user):
    """A provider may send distinct event ids that all say 'paid'."""
    payment = _payment(user, "VGH-PAY-MULTIEV1", "40.00")
    deliveries = [
        payment_mock.build_webhook(reference=payment.reference, amount="40.00",
                                   event_id=f"evt_{index}")
        for index in range(5)
    ]

    results = run_concurrently(lambda index: _deliver(*deliveries[index]), 5)

    assert all(result[0] == "ok" for result in results), results
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("40.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == 1
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.credited_at is not None


def test_concurrent_deposits_into_one_wallet_all_land(user):
    """Different payments crediting one wallet at once: nothing is lost to a
    read-modify-write race, and the ledger chain stays contiguous."""
    payments = [_payment(user, f"VGH-PAY-PARALL{index:02d}", "10.00") for index in range(6)]
    deliveries = [
        payment_mock.build_webhook(reference=p.reference, amount="10.00") for p in payments
    ]

    results = run_concurrently(lambda index: _deliver(*deliveries[index]), 6)

    assert all(result == ("ok", "processed") for result in results), results
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("60.00")
    sequences = list(WalletLedgerEntry.objects.filter(wallet=wallet)
                     .order_by("sequence").values_list("sequence", flat=True))
    assert sequences == list(range(sequences[0], sequences[0] + 6))
    assert verify_wallet_integrity(wallet)["ok"]


def test_a_payment_reference_can_never_be_reused(user, other_user):
    _payment(user, "VGH-PAY-UNIQUE01")
    with pytest.raises(IntegrityError), transaction.atomic():
        _payment(other_user, "VGH-PAY-UNIQUE01")


def test_deposit_and_purchase_racing_on_one_wallet_stay_consistent(user, catalog,
                                                                   funded_wallet):
    price = _price()
    wallet = funded_wallet(user, str(price))
    payment = _payment(user, "VGH-PAY-MIXRACE1", "30.00")
    raw, headers = payment_mock.build_webhook(reference=payment.reference, amount="30.00")

    def act(index):
        if index == 0:
            return _deliver(raw, headers)
        return buy(user.pk, "mixed-race")

    results = run_concurrently(act, 2)

    assert all(result[0] == "ok" for result in results), results
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("30.00")
    assert verify_wallet_integrity(wallet)["ok"]


def _price() -> Decimal:
    from apps.orders.services import quote

    return Decimal(str(quote("instagram", "US")["price"]))
