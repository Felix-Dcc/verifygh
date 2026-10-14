"""Referrals that pay only after real money (14 Oct 2026).

* The friend's welcome bonus waits for their own first top-up, not just an
  email - an email alone, instant with Google, let throwaway accounts farm it.
* The inviter earns credit too, but only once that friend has completed a
  number paid at least partly in cash.
* One inbox is one person: Gmail dots and +tags no longer make a "new" friend.
* The inviter is told when a friend joins and when they earn.
* Staff see what invited people went on to do, and what it cost.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.models import SecurityToken, User
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus, RefundStatus
from apps.orders.services import poll_order
from apps.payments.mock import build_webhook
from apps.referrals.models import (
    Referral,
    ReferralProgram,
    ReferralReward,
    ReferralStatus,
    ReferrerReward,
    RiskKind,
)
from apps.referrals.services import (
    canonical_email,
    code_for,
    has_received_signup_bonus,
    issue_referrer_reward,
    issue_reward,
)
from apps.verification import mock as verification_mock
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
CONFIRM = "/api/v1/auth/email/verify/confirm/"
PASSWORD = "Correct-Horse-Battery-1"
FRIEND = "abena@example.com"
BONUS = Decimal("2.00")
REFERRER_BONUS = Decimal("3.00")

_on_commit = None


@pytest.fixture(autouse=True)
def _commit_hooks(django_capture_on_commit_callbacks):
    global _on_commit
    _on_commit = django_capture_on_commit_callbacks
    yield
    _on_commit = None


@pytest.fixture
def gated():
    """The production rules: the friend's bonus waits for a GH₵10 top-up."""
    program = ReferralProgram.load()
    ReferralProgram.objects.filter(pk=program.pk).update(
        is_enabled=True, signup_bonus=BONUS, require_first_deposit=True,
        min_first_deposit=Decimal("10.00"), referrer_bonus=REFERRER_BONUS,
    )
    return ReferralProgram.load()


@pytest.fixture
def capture_token(monkeypatch):
    captured = {}
    original = SecurityToken.issue

    def spy(user, purpose, ttl_hours, ip=None, **options):
        token, raw = original(user, purpose, ttl_hours, ip, **options)
        captured[user.email] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))
    return captured


def register(api, *, code, email=FRIEND):
    with _on_commit(execute=True):
        response = api.post(REGISTER, {"email": email, "password": PASSWORD,
                                       "full_name": "Abena Mensah", "accepted_terms": True,
                                       "referral_code": code}, format="json")
    assert response.status_code == 201, response.data
    return User.objects.get(email=email)


def verify(api, captured, email=FRIEND):
    with _on_commit(execute=True):
        assert api.post(CONFIRM, {"token": captured[email]}, format="json").status_code == 200


def deposit(client, api, amount):
    """A real top-up: started by the customer, settled by the provider's webhook."""
    reference = client.post("/api/v1/payments/deposit/", {"amount": amount, "phone": "0241234567"},
                            format="json").data["reference"]
    raw, headers = build_webhook(reference=reference, amount=amount)
    with _on_commit(execute=True):
        response = api.post("/api/v1/payments/webhooks/mock/", data=raw,
                            content_type="application/json",
                            HTTP_X_MOCK_SIGNATURE=headers["X-Mock-Signature"])
    assert response.status_code == 200, response.data


def signed_up_friend(api, auth, inviter, captured):
    friend = register(api, code=code_for(inviter).code)
    verify(api, captured)
    friend.refresh_from_db()
    return friend, auth(friend, PASSWORD)


def buy_and_complete(client, friend):
    """The friend buys a number (promo first, then cash), gets a code and finishes."""
    verification_mock.force_scenario("HAPPY")
    with _on_commit(execute=True):  # the provider is asked after the order commits
        response = client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                               format="json")
    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])
    verification_mock.fast_forward(order.provider_order_id, 30)
    order = poll_order(Order.objects.get(pk=order.pk))
    assert order.status == OrderStatus.CODE_RECEIVED
    with _on_commit(execute=True):
        assert client.post(f"/api/v1/orders/{order.reference}/complete/").status_code == 200
    order.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# Production defaults
# ---------------------------------------------------------------------------


def test_production_ships_with_the_deposit_gate_and_an_inviter_reward():
    from config.settings import base

    assert base.VERIFYGH["REFERRAL_REQUIRE_FIRST_DEPOSIT"] is True
    assert Decimal(base.VERIFYGH["REFERRAL_SIGNUP_BONUS"]) == Decimal("2.00")
    assert Decimal(base.VERIFYGH["REFERRAL_MIN_FIRST_DEPOSIT"]) == Decimal("10.00")
    assert Decimal(base.VERIFYGH["REFERRAL_REFERRER_BONUS"]) == Decimal("3.00")


# ---------------------------------------------------------------------------
# 1. The friend's bonus waits for their own money
# ---------------------------------------------------------------------------


def test_a_verified_email_alone_no_longer_earns_the_bonus(gated, api, user, capture_token):
    friend = register(api, code=code_for(user).code)
    verify(api, capture_token)

    referral = Referral.objects.get(referred_user=friend)
    assert referral.status == ReferralStatus.PENDING
    assert "Top up" in referral.reason
    assert get_or_create_wallet(friend).promo_balance == Decimal("0.00")


def test_the_first_top_up_unlocks_the_bonus(gated, api, auth, user, capture_token):
    friend, client = signed_up_friend(api, auth, user, capture_token)

    deposit(client, api, "10.00")

    referral = Referral.objects.get(referred_user=friend)
    assert referral.status == ReferralStatus.REWARDED
    wallet = get_or_create_wallet(friend)
    assert wallet.promo_balance == BONUS and wallet.balance == Decimal("10.00")
    assert verify_wallet_integrity(wallet)["ok"]


def test_top_ups_count_together_towards_the_minimum(gated, api, auth, user, capture_token):
    ReferralProgram.objects.update(min_first_deposit=Decimal("20.00"))
    friend, client = signed_up_friend(api, auth, user, capture_token)

    deposit(client, api, "10.00")
    assert Referral.objects.get(referred_user=friend).status == ReferralStatus.PENDING

    deposit(client, api, "10.00")
    assert Referral.objects.get(referred_user=friend).status == ReferralStatus.REWARDED


def test_staff_credit_is_not_a_top_up(gated, api, auth, user, capture_token):
    from apps.wallet.services import adjust

    friend, _client = signed_up_friend(api, auth, user, capture_token)
    adjust(wallet=get_or_create_wallet(friend), amount=Decimal("50.00"), direction="CREDIT",
           idempotency_key="goodwill", reason="Goodwill credit", admin=user)
    from apps.referrals.services import process_for_user

    process_for_user(friend)
    assert Referral.objects.get(referred_user=friend).status == ReferralStatus.PENDING


def test_the_friend_is_told_how_to_get_the_bonus(gated, api, user, capture_token):
    friend = register(api, code=code_for(user).code)

    notice = Notification.objects.get(user=friend, title="Your welcome bonus is waiting")
    assert "GH₵" in notice.body and "10.00" in notice.body


# ---------------------------------------------------------------------------
# 2. The inviter earns once the friend pays
# ---------------------------------------------------------------------------


def test_the_inviter_earns_when_the_friends_first_paid_number_completes(
        gated, api, auth, user, capture_token, catalog):
    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    assert get_or_create_wallet(user).promo_balance == Decimal("0.00")

    order = buy_and_complete(client, friend)

    assert order.promo_amount == BONUS and order.cash_amount > 0
    reward = ReferrerReward.objects.get(referral__referred_user=friend)
    assert reward.user == user and reward.amount == REFERRER_BONUS
    assert reward.qualifying_order_id == order.pk
    wallet = get_or_create_wallet(user)
    assert wallet.promo_balance == REFERRER_BONUS and wallet.balance == Decimal("0.00")
    assert verify_wallet_integrity(wallet)["ok"]
    entry = WalletLedgerEntry.objects.get(wallet=wallet, entry_type=LedgerEntryType.REFERRAL_BONUS)
    assert entry.idempotency_key == f"referrer-reward:{reward.referral_id}"
    earned = Notification.objects.get(user=user, channel="EMAIL", title__startswith="You earned")
    assert "3.00" in earned.title and "a***@example.com" in earned.body


def test_the_inviter_is_paid_once_however_often_it_is_asked(
        gated, api, auth, user, capture_token, catalog):
    from apps.referrals.tasks import process_pending_referrals

    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    buy_and_complete(client, friend)
    referral = Referral.objects.get(referred_user=friend)

    first = ReferrerReward.objects.get(referral=referral)
    assert issue_referrer_reward(referral).pk == first.pk
    process_pending_referrals()
    buy_and_complete(client, friend)

    assert ReferrerReward.objects.filter(referral=referral).count() == 1
    assert get_or_create_wallet(user).promo_balance == REFERRER_BONUS


def test_a_number_bought_with_promo_alone_or_refunded_earns_nothing(
        gated, api, auth, user, capture_token, catalog):
    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    ReferralProgram.objects.update(referrer_bonus=Decimal("0.00"))  # hold it while we set up
    order = buy_and_complete(client, friend)
    ReferralProgram.objects.update(referrer_bonus=REFERRER_BONUS)
    referral = Referral.objects.get(referred_user=friend)

    Order.objects.filter(pk=order.pk).update(cash_amount=Decimal("0.00"))
    assert issue_referrer_reward(referral) is None
    Order.objects.filter(pk=order.pk).update(cash_amount=Decimal("1.00"),
                                             refund_status=RefundStatus.COMPLETED)
    assert issue_referrer_reward(referral) is None
    assert not ReferrerReward.objects.exists()


def test_no_inviter_reward_while_the_friends_bonus_is_withdrawn(
        gated, api, auth, user, admin_user, capture_token, catalog):
    from apps.referrals.services import reverse_reward

    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    reverse_reward(ReferralReward.objects.get(user=friend), admin=admin_user,
                   reason="Second account of an existing customer")

    buy_and_complete(client, friend)

    assert not ReferrerReward.objects.exists()
    assert get_or_create_wallet(user).promo_balance == Decimal("0.00")


def test_an_inviters_reward_is_not_a_welcome_bonus(gated, api, auth, user, capture_token,
                                                   catalog):
    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    buy_and_complete(client, friend)

    assert ReferrerReward.objects.filter(user=user).exists()
    # The inviter can still be welcomed if someone invited them in turn.
    assert has_received_signup_bonus(user) is False


def test_an_admin_override_cannot_pay_a_second_welcome_bonus(gated, api, auth, user,
                                                            capture_token):
    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "10.00")
    referral = Referral.objects.get(referred_user=friend)
    ReferralReward.objects.filter(referral=referral).delete()  # a reward row lost
    Referral.objects.filter(pk=referral.pk).update(status=ReferralStatus.FRAUD_FLAGGED)
    referral.refresh_from_db()

    # The ledger still shows the bonus, so even a forced approval refuses.
    assert issue_reward(referral, force=True) is None
    assert get_or_create_wallet(friend).promo_balance == BONUS


# ---------------------------------------------------------------------------
# 4. One inbox, one person
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("address", "inbox"), [
    ("Sally.Bryan@gmail.com", "sallybryan@gmail.com"),
    ("sallybryan+promo2@googlemail.com", "sallybryan@gmail.com"),
    ("s.a.l.l.y.bryan+x@GMAIL.COM", "sallybryan@gmail.com"),
    ("kwame+shop@example.com", "kwame@example.com"),
    ("kwame.mensah@example.com", "kwame.mensah@example.com"),  # dots matter outside Gmail
])
def test_addresses_reduce_to_their_inbox(address, inbox):
    assert canonical_email(address) == inbox


def test_a_gmail_alias_of_an_existing_account_is_held(gated, api, user, capture_token):
    User.objects.create_user(email="sally.bryan@gmail.com", password=PASSWORD,
                             is_email_verified=True)
    friend = register(api, code=code_for(user).code, email="sallybryan+2@googlemail.com")

    referral = Referral.objects.get(referred_user=friend)
    flag = referral.risk_flags.get(kind=RiskKind.EMAIL_ALIAS)
    assert flag.blocking is True


def test_the_inviters_own_inbox_under_another_spelling_is_caught(api, capture_token):
    inviter = User.objects.create_user(email="kwame.mensah@gmail.com", password=PASSWORD,
                                       is_email_verified=True)
    friend = register(api, code=code_for(inviter).code, email="kwamemensah+2@gmail.com")

    referral = Referral.objects.get(referred_user=friend)
    assert referral.risk_flags.filter(kind=RiskKind.SHARED_EMAIL, blocking=True).exists()


def test_a_different_person_on_the_same_domain_is_not_flagged(gated, api, user, capture_token):
    User.objects.create_user(email="ama.owusu@gmail.com", password=PASSWORD)
    friend = register(api, code=code_for(user).code, email="ama.osei@gmail.com")

    assert not Referral.objects.get(referred_user=friend).risk_flags.filter(
        kind=RiskKind.EMAIL_ALIAS).exists()


# ---------------------------------------------------------------------------
# 5. The inviter hears about it
# ---------------------------------------------------------------------------


def test_the_inviter_is_emailed_when_a_friend_joins(gated, api, user, capture_token):
    register(api, code=code_for(user).code)

    joined = Notification.objects.filter(user=user, title="A friend joined with your link")
    assert set(joined.values_list("channel", flat=True)) == {"EMAIL", "IN_APP"}
    body = joined.first().body
    assert "a***@example.com" in body and FRIEND not in body
    assert "3.00" in body


# ---------------------------------------------------------------------------
# 6. What staff can see
# ---------------------------------------------------------------------------


def test_staff_see_what_invited_people_went_on_to_do(gated, api, auth, user, admin_user,
                                                    capture_token, catalog):
    friend, client = signed_up_friend(api, auth, user, capture_token)
    deposit(client, api, "50.00")
    order = buy_and_complete(client, friend)

    data = auth(admin_user, "Correct-Horse-Battery-3").get(
        "/api/v1/admin/referrals-analytics/").data

    assert data["registrations"] == 1
    assert data["invited_verified"] == 1 and data["invited_topped_up"] == 1
    assert data["invited_topped_up_rate"] == 100.0
    assert data["invited_buyers"] == 1 and data["invited_repeat_buyers"] == 0
    assert Decimal(data["invited_cash_revenue"]) == order.cash_amount
    assert Decimal(data["invited_revenue"]) == order.price
    assert Decimal(data["referrer_credit_issued"]) == REFERRER_BONUS
    assert Decimal(data["total_bonus_cost"]) == BONUS + REFERRER_BONUS


def test_the_offer_shown_to_customers_carries_every_term(gated, api, user, auth):
    data = api.post("/api/v1/referrals/validate/", {"code": code_for(user).code},
                    format="json").data
    assert data["valid"] is True
    assert data["bonus_amount"] == "2.00" and data["referrer_bonus"] == "3.00"
    assert data["require_first_deposit"] is True and data["min_first_deposit"] == "10.00"

    mine = auth(user).get("/api/v1/referrals/me/").data
    assert mine["referrer_bonus"] == "3.00" and mine["stats"]["earned"] == "0.00"


def test_a_busy_group_post_is_not_held_for_speed(gated, api, user, capture_token):
    """40 sign-ups an hour per link (was 5): a WhatsApp group post is normal."""
    program = ReferralProgram.load()
    assert program.velocity_per_hour == 40
    # A full hour at that speed fits inside one month's paid bonuses.
    assert program.max_monthly_successful_referrals == 40
    from apps.referrals.services import attach_referral

    code = code_for(user).code
    for index in range(8):
        member = User.objects.create_user(email=f"groupmember{index}@example.com",
                                          password=PASSWORD)
        with _on_commit(execute=True):
            assert attach_referral(new_user=member, raw_code=code) is not None

    assert Referral.objects.filter(referrer=user).count() == 8
    assert not Referral.objects.filter(risk_flags__kind=RiskKind.REFERRER_VELOCITY).exists()
