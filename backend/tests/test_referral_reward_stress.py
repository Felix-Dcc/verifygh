"""A deliberately hostile run at the reward path.

Everything the specification warns about, at once: twenty threads racing to
reward the same referral, a second wave replaying it after it has settled, and
a third user's referral running alongside to prove the lock is per referral
and not a global bottleneck.

Run as part of the normal suite; CI runs it against PostgreSQL 16.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import connection, connections

from apps.accounts.models import User
from apps.referrals.models import Referral, ReferralReward, ReferralStatus
from apps.referrals.services import code_for, issue_reward
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db(transaction=True)

BONUS = Decimal("5.00")
THREADS = 20


def _referral(referrer, email):
    friend = User.objects.create_user(email=email, password="Correct-Horse-Battery-1",
                                      is_email_verified=True)
    return Referral.objects.create(referrer=referrer, referred_user=friend,
                                   code=code_for(referrer).code,
                                   status=ReferralStatus.ELIGIBLE)


def _hammer(referral_ids: list, rounds: int = 1) -> list:
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(referral_ids) * THREADS)

    def worker(referral_id):
        try:
            barrier.wait(timeout=20)
            for _ in range(rounds):
                reward = issue_reward(Referral.objects.get(pk=referral_id))
                with lock:
                    results.append(getattr(reward, "reference", None))
        except Exception as exc:  # noqa: BLE001
            with lock:
                results.append(f"error:{exc!r}")
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=worker, args=(referral_id,))
        for referral_id in referral_ids
        for _ in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def test_twenty_threads_on_one_referral_issue_one_bonus(user):
    referral = _referral(user, "stress@example.com")

    results = _hammer([referral.pk], rounds=2)

    assert not [r for r in results if isinstance(r, str) and r.startswith("error:")], results
    friend = referral.referred_user
    wallet = get_or_create_wallet(friend)
    assert wallet.promo_balance == BONUS, f"expected one bonus, got {wallet.promo_balance}"
    assert ReferralReward.objects.filter(referral=referral).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.REFERRAL_BONUS).count() == 1
    assert len({r for r in results if r}) == 1  # one reward reference, shared by all
    assert verify_wallet_integrity(wallet)["ok"]


def test_replaying_after_it_settled_changes_nothing(user):
    referral = _referral(user, "replay@example.com")
    issue_reward(referral)
    wallet = get_or_create_wallet(referral.referred_user)
    assert wallet.promo_balance == BONUS

    _hammer([referral.pk], rounds=2)

    wallet.refresh_from_db()
    assert wallet.promo_balance == BONUS
    assert ReferralReward.objects.filter(referral=referral).count() == 1


def test_separate_referrals_settle_independently_under_load(user, other_user):
    first = _referral(user, "parallel1@example.com")
    second = _referral(other_user, "parallel2@example.com")

    results = _hammer([first.pk, second.pk])

    assert not [r for r in results if isinstance(r, str) and r.startswith("error:")], results
    for referral in (first, second):
        wallet = get_or_create_wallet(referral.referred_user)
        assert wallet.promo_balance == BONUS
        assert ReferralReward.objects.filter(referral=referral).count() == 1
    assert ReferralReward.objects.count() == 2


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL only")
def test_the_referral_row_is_locked_while_rewarding(user):
    """The lock the idempotency argument relies on is really taken."""
    from django.test.utils import CaptureQueriesContext

    referral = _referral(user, "locked@example.com")
    with CaptureQueriesContext(connection) as queries:
        issue_reward(referral)

    locking = [q["sql"] for q in queries.captured_queries
               if "FOR UPDATE" in q["sql"] and Referral._meta.db_table in q["sql"]]
    assert locking, "issue_reward did not SELECT ... FOR UPDATE the referral row"
