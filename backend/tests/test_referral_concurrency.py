"""Concurrency around the referral reward.

The scenario the specification names: call the reward ten times at once and
get one GH₵5 credit, not fifty. These run real threads on real connections.
On PostgreSQL the referral row lock serialises them; on SQLite the unique
constraints do. The assertions are on the invariant, so both are proven.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import connections

from apps.accounts.models import User
from apps.orders.models import Order
from apps.referrals.models import Referral, ReferralReward, ReferralStatus
from apps.referrals.services import code_for, issue_reward, process_for_user
from apps.wallet.models import FundType, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db(transaction=True)

BONUS = Decimal("5.00")
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

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.fixture
def pending_referral(user):
    friend = User.objects.create_user(email="concurrent@example.com", password=PASSWORD,
                                      is_email_verified=True)
    return Referral.objects.create(referrer=user, referred_user=friend,
                                   code=code_for(user).code, status=ReferralStatus.ELIGIBLE)


def promo_of(user) -> Decimal:
    return get_or_create_wallet(user).promo_balance


def bonus_entries(user):
    return WalletLedgerEntry.objects.filter(
        wallet__user=user, entry_type=LedgerEntryType.REFERRAL_BONUS
    )


def test_ten_concurrent_rewards_credit_exactly_one_bonus(pending_referral):
    """GH₵5 once, never GH₵50."""
    friend = pending_referral.referred_user

    results = run_concurrently(
        lambda index: issue_reward(Referral.objects.get(pk=pending_referral.pk)), 10
    )

    assert all(result[0] == "ok" for result in results), results
    assert promo_of(friend) == BONUS
    assert ReferralReward.objects.filter(referral=pending_referral).count() == 1
    assert bonus_entries(friend).count() == 1
    # Every thread that got a reward object got the *same* one.
    references = {result[1].reference for result in results if result[1] is not None}
    assert len(references) == 1
    assert verify_wallet_integrity(get_or_create_wallet(friend))["ok"]


def test_concurrent_verification_paths_credit_once(pending_referral):
    """The sweep, the verification hook and an admin can all fire at once."""
    friend = pending_referral.referred_user

    def act(index):
        if index % 2 == 0:
            return process_for_user(User.objects.get(pk=friend.pk))
        return issue_reward(Referral.objects.get(pk=pending_referral.pk), force=True)

    results = run_concurrently(act, 8)

    assert all(result[0] == "ok" for result in results), results
    assert promo_of(friend) == BONUS
    assert ReferralReward.objects.filter(referral=pending_referral).count() == 1
    assert bonus_entries(friend).count() == 1


def test_two_registrations_racing_on_one_code_each_get_their_own_referral(user):
    """Different accounts, same link: both attributions stand, one each."""
    from apps.referrals.services import attach_referral

    code = code_for(user).code
    friends = [
        User.objects.create_user(email=f"racer{index}@example.com", password=PASSWORD)
        for index in range(4)
    ]

    results = run_concurrently(
        lambda index: attach_referral(new_user=friends[index], raw_code=code, request=None), 4
    )

    assert all(result[0] == "ok" for result in results), results
    assert Referral.objects.filter(referrer=user).count() == 4


def test_one_account_cannot_be_attributed_twice_concurrently(user, other_user):
    """Two codes arriving at once for one new account: the first wins, for ever."""
    from apps.referrals.services import attach_referral

    friend = User.objects.create_user(email="contested@example.com", password=PASSWORD)
    codes = [code_for(user).code, code_for(other_user).code]

    run_concurrently(
        lambda index: attach_referral(
            new_user=User.objects.get(pk=friend.pk), raw_code=codes[index % 2], request=None
        ), 6
    )

    assert Referral.objects.filter(referred_user=friend).count() == 1


def test_promotional_credit_cannot_be_spent_twice_concurrently(user, catalog, funded_wallet):
    """Two purchases at once, with only enough promotional credit for one."""
    from apps.common.errors import APIError
    from apps.orders.services import create_order, quote

    price = Decimal(quote("instagram", "US")["price"])
    # Exactly one order's worth, all of it promotional.
    from apps.wallet.services import post_entry

    post_entry(wallet=get_or_create_wallet(user), amount=price,
               entry_type=LedgerEntryType.REFERRAL_BONUS, direction="CREDIT",
               idempotency_key="promo-race", funds=FundType.PROMO)

    def buy(index):
        try:
            return create_order(user=User.objects.get(pk=user.pk), service_slug="instagram",
                                country_code="US", idempotency_key=f"race-{index}").reference
        except APIError as exc:
            return f"refused:{exc.code}"

    results = run_concurrently(buy, 2)

    outcomes = [result[1] for result in results]
    assert sum(1 for outcome in outcomes if str(outcome).startswith("refused")) == 1, results
    assert Order.objects.filter(user=user).count() == 1
    wallet = get_or_create_wallet(user)
    assert wallet.promo_balance == Decimal("0.00")
    assert wallet.balance == Decimal("0.00")
    assert verify_wallet_integrity(wallet)["ok"]
