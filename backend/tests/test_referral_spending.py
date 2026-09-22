"""Spending and refunding a wallet that holds both cash and promotional credit.

The rule this file exists to protect: **promotional credit never becomes
cash.** It is spent first, refunded to itself, and cannot leave the platform.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderStatus, Refund
from apps.orders.services import create_order, issue_refund, quote, split_refund
from apps.wallet.models import FundType, LedgerDirection, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, post_entry, verify_wallet_integrity

pytestmark = pytest.mark.django_db


def grant_promo(user, amount="5.00"):
    return post_entry(
        wallet=get_or_create_wallet(user), amount=Decimal(amount),
        entry_type=LedgerEntryType.REFERRAL_BONUS, direction=LedgerDirection.CREDIT,
        idempotency_key=f"promo:{amount}", funds=FundType.PROMO,
    )


def price() -> Decimal:
    return Decimal(quote("instagram", "US")["price"])


def buy(user, key="spend"):
    return create_order(user=user, service_slug="instagram", country_code="US",
                        idempotency_key=key)


def entries(user, funds=None):
    queryset = WalletLedgerEntry.objects.filter(wallet__user=user)
    return queryset.filter(funds=funds) if funds else queryset


def test_promotional_credit_is_spent_before_cash(user, catalog, funded_wallet):
    cost = price()
    funded_wallet(user, str(cost))
    grant_promo(user, "5.00")

    order = buy(user)

    order.refresh_from_db()
    assert order.promo_amount == Decimal("5.00")
    assert order.cash_amount == cost - Decimal("5.00")

    wallet = get_or_create_wallet(user)
    assert wallet.promo_balance == Decimal("0.00")
    assert wallet.balance == Decimal("5.00")  # the cash the bonus displaced
    assert entries(user, FundType.PROMO).filter(
        entry_type=LedgerEntryType.PURCHASE).count() == 1
    assert entries(user, FundType.CASH).filter(
        entry_type=LedgerEntryType.PURCHASE).count() == 1
    assert verify_wallet_integrity(wallet)["ok"]


def test_promotional_credit_alone_can_pay_for_an_order(user, catalog):
    cost = price()
    grant_promo(user, str(cost))

    order = buy(user)

    order.refresh_from_db()
    assert order.promo_amount == cost
    assert order.cash_amount == Decimal("0.00")
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("0.00")
    assert wallet.promo_balance == Decimal("0.00")
    assert order.debit_entry_id is None          # no cash entry was created
    assert order.promo_debit_entry_id is not None


def test_the_two_buckets_are_added_together_for_affordability(user, catalog, funded_wallet):
    cost = price()
    funded_wallet(user, str(cost - Decimal("4.00")))
    grant_promo(user, "5.00")

    order = buy(user)  # neither bucket alone could pay for this

    assert order.status == OrderStatus.PROCESSING
    assert get_or_create_wallet(user).spendable == Decimal("1.00")


def test_a_purchase_beyond_both_buckets_writes_nothing(user, catalog):
    from apps.common.errors import InsufficientFunds

    grant_promo(user, "3.00")

    with pytest.raises(InsufficientFunds) as excinfo:
        buy(user)

    assert not Order.objects.exists()
    wallet = get_or_create_wallet(user)
    assert wallet.promo_balance == Decimal("3.00")
    assert entries(user).filter(entry_type=LedgerEntryType.PURCHASE).count() == 0
    assert "spendable" in excinfo.value.details


def test_a_refund_returns_each_bucket_to_itself(user, catalog, funded_wallet):
    """The crucial one: a refunded promotional purchase must not become cash."""
    cost = price()
    funded_wallet(user, str(cost))
    grant_promo(user, "5.00")
    order = buy(user)
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.FAILED)

    issue_refund(Order.objects.get(pk=order.pk), reason="PROVIDER_FAILED")

    wallet = get_or_create_wallet(user)
    assert wallet.balance == cost            # exactly the cash they put in
    assert wallet.promo_balance == Decimal("5.00")  # and the bonus, still a bonus
    refund = Refund.objects.get(order=order)
    assert refund.promo_amount == Decimal("5.00")
    assert refund.cash_amount == cost - Decimal("5.00")
    assert verify_wallet_integrity(wallet)["ok"]


def test_a_partial_refund_never_returns_more_cash_than_its_share(user, catalog, funded_wallet):
    cost = price()
    funded_wallet(user, str(cost))
    grant_promo(user, "5.00")
    order = buy(user)
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.FAILED)
    order.refresh_from_db()

    half = (cost / 2).quantize(Decimal("0.01"))
    promo_part, cash_part = split_refund(order, half)

    assert promo_part + cash_part == half
    # Rounding goes to the promotional side, so cash is never over-returned.
    assert cash_part <= (half * order.cash_amount / cost).quantize(Decimal("0.01"))

    issue_refund(order, reason="ADMIN_GOODWILL", amount=half, automatic=False)
    wallet = get_or_create_wallet(user)
    assert wallet.balance == cost - order.cash_amount + cash_part
    assert wallet.promo_balance == promo_part


def test_an_order_paid_only_with_cash_refunds_only_cash(user, catalog, funded_wallet):
    cost = price()
    funded_wallet(user, str(cost))
    order = buy(user)
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.FAILED)

    issue_refund(Order.objects.get(pk=order.pk), reason="PROVIDER_FAILED")

    wallet = get_or_create_wallet(user)
    assert wallet.balance == cost
    assert wallet.promo_balance == Decimal("0.00")
    assert not entries(user, FundType.PROMO).exists()


def test_orders_placed_before_promotional_credit_existed_still_refund(user, catalog,
                                                                     funded_wallet):
    """Rows written by the old code have no split recorded; they are cash."""
    cost = price()
    funded_wallet(user, str(cost))
    order = buy(user)
    # Simulate a legacy row: the split columns were added by this migration.
    Order.objects.filter(pk=order.pk).update(
        status=OrderStatus.FAILED, promo_amount=Decimal("0.00"), cash_amount=Decimal("0.00")
    )

    issue_refund(Order.objects.get(pk=order.pk), reason="PROVIDER_FAILED")

    wallet = get_or_create_wallet(user)
    assert wallet.balance == cost
    assert wallet.promo_balance == Decimal("0.00")


def test_spending_promotional_credit_does_not_count_as_a_deposit(user, catalog, funded_wallet):
    """Promotional credit must never inflate the numbers that describe real money."""
    cost = price()
    funded_wallet(user, str(cost))
    wallet = get_or_create_wallet(user)
    deposited_before = wallet.total_deposited
    grant_promo(user, "5.00")

    buy(user)

    wallet.refresh_from_db()
    assert wallet.total_deposited == deposited_before  # a bonus is not a deposit
    assert wallet.promo_granted == Decimal("5.00")
