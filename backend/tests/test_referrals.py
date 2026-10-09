"""The referral programme, from an invite link to promotional credit.

These tests drive the real endpoints - register, verify, buy, refund - because
the value of a referral system is entirely in what it refuses to do, and the
refusals live in the service and database layers, not in a helper.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import SecurityToken, User
from apps.referrals.models import (
    Referral,
    ReferralCode,
    ReferralProgram,
    ReferralReward,
    ReferralStatus,
    RiskKind,
)
from apps.referrals.services import code_for
from apps.wallet.models import FundType, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

#: Registration queues the verification email with transaction.on_commit, and
#: the reward itself queues a notification the same way. Run those callbacks so
#: the tests exercise the real post-commit path.
_capture_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture_on_commit
    _capture_on_commit = django_capture_on_commit_callbacks
    yield
    _capture_on_commit = None


REGISTER = "/api/v1/auth/register/"
CONFIRM = "/api/v1/auth/email/verify/confirm/"
PASSWORD = "Correct-Horse-Battery-1"
BONUS = Decimal("5.00")
#: The invited friend. Deliberately not one of conftest's users.
FRIEND = "abena@example.com"


@pytest.fixture
def capture_token(monkeypatch):
    """The raw verification token, which only ever exists in the email."""
    captured = {}
    original = SecurityToken.issue

    def spy(user, purpose, ttl_hours, ip=None, **options):
        token, raw = original(user, purpose, ttl_hours, ip, **options)
        captured[user.email] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))
    return captured


def register(api, email=FRIEND, code=None, phone="", **extra):
    body = {"email": email, "password": PASSWORD, "full_name": "Abena Mensah",
            "accepted_terms": True, **extra}
    if code is not None:
        body["referral_code"] = code
    if phone:
        body["phone"] = phone
    with _capture_on_commit(execute=True):
        return api.post(REGISTER, body, format="json")


def verify(api, captured, email=FRIEND):
    with _capture_on_commit(execute=True):
        return api.post(CONFIRM, {"token": captured[email]}, format="json")


def promo_balance(user) -> Decimal:
    return get_or_create_wallet(user).promo_balance


def referral_of(email=FRIEND) -> Referral:
    return Referral.objects.get(referred_user__email=email)


# ---------------------------------------------------------------------------
# Codes and attribution
# ---------------------------------------------------------------------------


def test_every_user_gets_a_unique_unguessable_code(user, other_user):
    first = code_for(user).code
    second = code_for(other_user).code

    assert first != second
    assert first.startswith("VGH") and len(first) == 8
    # No ambiguous characters: a code read off a phone screen is unambiguous.
    assert not set(first[3:]) & set("O0I1")
    assert code_for(user).code == first  # stable, never regenerated


def test_a_user_cannot_choose_or_change_their_code(user, auth):
    original = code_for(user).code
    client = auth(user)

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/v1/referrals/me/", {"code": "VGHMINE1"},
                                           format="json")
        assert response.status_code == 405, method
    assert ReferralCode.objects.get(user=user).code == original


def test_registering_through_a_link_stores_the_attribution(api, user):
    code = code_for(user).code
    assert register(api, code=code).status_code == 201

    referral = referral_of()
    assert referral.referrer == user
    assert referral.code == code
    assert referral.status == ReferralStatus.PENDING
    assert promo_balance(referral.referred_user) == Decimal("0.00")  # not yet eligible


def test_the_code_is_case_and_space_insensitive(api, user):
    code = code_for(user).code
    assert register(api, code=f"  {code.lower()} ").status_code == 201
    assert referral_of().referrer == user


def test_an_unknown_code_is_ignored_and_registration_still_works(api):
    response = register(api, code="VGHZZZZZ")

    assert response.status_code == 201
    assert not Referral.objects.exists()
    assert User.objects.filter(email=FRIEND).exists()


def test_registration_without_a_code_creates_no_referral(api):
    assert register(api).status_code == 201
    assert not Referral.objects.exists()


def test_the_referrer_cannot_be_changed_after_registration(api, user, other_user, auth):
    """The attribution is written once, by the backend, and never moves."""
    code_for(user)
    assert register(api, code=code_for(user).code).status_code == 201
    referred = User.objects.get(email=FRIEND)

    # Re-registering, re-sending the field, or a second attribution attempt.
    from apps.referrals.services import attach_referral

    attach_referral(new_user=referred, raw_code=code_for(other_user).code, request=None)

    assert Referral.objects.filter(referred_user=referred).count() == 1
    assert referral_of().referrer == user


def test_a_referral_code_cannot_be_used_by_its_owner(api, user, auth):
    """Self-referral is refused by the database, not only by the service."""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Referral.objects.create(referrer=user, referred_user=user, code=code_for(user).code)


# ---------------------------------------------------------------------------
# Eligibility and the reward
# ---------------------------------------------------------------------------


def test_the_bonus_arrives_only_after_email_verification(api, user, capture_token):
    register(api, code=code_for(user).code)
    referred = User.objects.get(email=FRIEND)

    assert referral_of().status == ReferralStatus.PENDING
    assert promo_balance(referred) == Decimal("0.00")

    assert verify(api, capture_token).status_code == 200

    referral = referral_of()
    assert referral.status == ReferralStatus.REWARDED
    assert promo_balance(referred) == BONUS
    assert referral.reward.amount == BONUS


def test_the_bonus_is_one_ledger_entry_of_promotional_funds(api, user, capture_token):
    register(api, code=code_for(user).code)
    verify(api, capture_token)
    referred = User.objects.get(email=FRIEND)

    entries = WalletLedgerEntry.objects.filter(wallet__user=referred)
    assert entries.count() == 1
    entry = entries.get()
    assert entry.entry_type == LedgerEntryType.REFERRAL_BONUS
    assert entry.funds == FundType.PROMO
    assert entry.amount == BONUS
    assert entry.balance_after == BONUS

    wallet = get_or_create_wallet(referred)
    assert wallet.balance == Decimal("0.00")      # no cash was created
    assert wallet.promo_granted == BONUS
    assert verify_wallet_integrity(wallet)["ok"]


def test_running_the_reward_again_does_nothing(api, user, capture_token):
    from apps.referrals.services import issue_reward

    register(api, code=code_for(user).code)
    verify(api, capture_token)
    referred = User.objects.get(email=FRIEND)

    for _ in range(10):
        issue_reward(referral_of(), force=True)

    assert promo_balance(referred) == BONUS
    assert ReferralReward.objects.filter(referral=referral_of()).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet__user=referred, entry_type=LedgerEntryType.REFERRAL_BONUS).count() == 1


def test_an_account_that_already_had_a_signup_bonus_is_not_bonused_again(api, user,
                                                                         capture_token):
    """One signup bonus per account, whoever invited them and however the
    first one was granted - the check reads the ledger, not just our table."""
    from apps.wallet.services import post_entry

    register(api, code=code_for(user).code)
    referred = User.objects.get(email=FRIEND)
    post_entry(wallet=get_or_create_wallet(referred), amount=BONUS,
               entry_type=LedgerEntryType.REFERRAL_BONUS, direction="CREDIT",
               idempotency_key="earlier-campaign", funds=FundType.PROMO)

    verify(api, capture_token)

    referral = referral_of()
    assert referral.status == ReferralStatus.REJECTED
    assert referral.risk_flags.filter(kind=RiskKind.ALREADY_BONUSED).exists()
    assert promo_balance(referred) == BONUS  # still just the one
    assert not ReferralReward.objects.filter(user=referred).exists()


def test_a_suspended_account_is_not_rewarded(api, user, capture_token):
    register(api, code=code_for(user).code)
    referred = User.objects.get(email=FRIEND)
    User.objects.filter(pk=referred.pk).update(is_suspended=True)

    verify(api, capture_token)

    assert referral_of().status == ReferralStatus.REJECTED
    assert promo_balance(referred) == Decimal("0.00")


def test_a_suspended_referrers_invitation_is_not_rewarded(api, user, capture_token):
    register(api, code=code_for(user).code)
    User.objects.filter(pk=user.pk).update(is_suspended=True)

    verify(api, capture_token)

    assert referral_of().status == ReferralStatus.REJECTED
    assert promo_balance(User.objects.get(email=FRIEND)) == Decimal("0.00")


def test_a_paused_programme_attributes_nothing(api, user, settings):
    program = ReferralProgram.load()
    ReferralProgram.objects.filter(pk=program.pk).update(is_enabled=False)

    assert register(api, code=code_for(user).code).status_code == 201
    assert not Referral.objects.exists()


def test_the_bonus_amount_follows_the_configured_programme(api, user, capture_token):
    program = ReferralProgram.load()
    ReferralProgram.objects.filter(pk=program.pk).update(signup_bonus=Decimal("12.50"))

    register(api, code=code_for(user).code)
    verify(api, capture_token)

    assert promo_balance(User.objects.get(email=FRIEND)) == Decimal("12.50")


def test_the_monthly_limit_holds_further_referrals(api, user, capture_token):
    program = ReferralProgram.load()
    ReferralProgram.objects.filter(pk=program.pk).update(max_monthly_successful_referrals=1)

    # One rewarded referral this month already.
    first = User.objects.create_user(email="first@example.com", password=PASSWORD)
    Referral.objects.create(referrer=user, referred_user=first, code=code_for(user).code,
                            status=ReferralStatus.REWARDED, rewarded_at=timezone.now())

    register(api, code=code_for(user).code)
    verify(api, capture_token)

    referral = referral_of()
    assert referral.status == ReferralStatus.PENDING  # held, not rejected
    assert promo_balance(User.objects.get(email=FRIEND)) == Decimal("0.00")
    assert referral.risk_flags.filter(kind=RiskKind.MONTHLY_LIMIT).exists()


# ---------------------------------------------------------------------------
# Anti-abuse
# ---------------------------------------------------------------------------


def test_reusing_the_referrers_phone_number_is_blocked_at_registration(api, user):
    """The account cannot even be created with someone else's number."""
    response = register(api, code=code_for(user).code, phone="0241234567")

    assert response.status_code == 400
    assert "phone" in str(response.data).lower()


def test_a_second_account_on_the_referrers_device_is_held_for_review(api, user, capture_token):
    """A shared laptop is not proof of fraud, so it is held, never auto-rejected."""
    from apps.accounts.models import UserDevice

    agent = "Mozilla/5.0 (Linux; Android 14) VerifyGH-Test"
    UserDevice.objects.create(
        user=user, fingerprint_hash=UserDevice.fingerprint(agent, "127.0.0.1"),
        last_ip="127.0.0.1",
    )

    api.credentials(HTTP_USER_AGENT=agent)
    register(api, code=code_for(user).code)
    verify(api, capture_token)

    referral = referral_of()
    assert referral.status == ReferralStatus.FRAUD_FLAGGED
    assert referral.risk_flags.filter(kind=RiskKind.SHARED_DEVICE).exists()
    assert promo_balance(User.objects.get(email=FRIEND)) == Decimal("0.00")


def test_a_shared_ip_address_alone_never_blocks_a_reward(api, user, capture_token):
    """Homes, offices, schools and mobile networks share addresses in Ghana."""
    User.objects.filter(pk=user.pk).update(signup_ip="127.0.0.1")

    register(api, code=code_for(user).code)
    verify(api, capture_token)

    referral = referral_of()
    assert referral.status == ReferralStatus.REWARDED
    assert promo_balance(User.objects.get(email=FRIEND)) == BONUS
    flag = referral.risk_flags.get(kind=RiskKind.SHARED_IP)
    assert flag.blocking is False  # recorded for context, not acted on


def test_a_burst_of_signups_from_one_referrer_is_held(api, user, capture_token):
    program = ReferralProgram.load()
    ReferralProgram.objects.filter(pk=program.pk).update(velocity_per_hour=2)

    for index in range(2):
        friend = User.objects.create_user(email=f"burst{index}@example.com", password=PASSWORD)
        Referral.objects.create(referrer=user, referred_user=friend, code=code_for(user).code)

    register(api, code=code_for(user).code)
    verify(api, capture_token)

    referral = referral_of()
    assert referral.status == ReferralStatus.FRAUD_FLAGGED
    assert referral.risk_flags.filter(kind=RiskKind.REFERRER_VELOCITY).exists()


# ---------------------------------------------------------------------------
# What promotional credit may and may not do
# ---------------------------------------------------------------------------


def test_promotional_credit_cannot_be_withdrawn(user):
    """There is no withdrawal endpoint yet; the ledger already refuses one."""
    from apps.common.errors import ValidationFailed
    from apps.wallet.models import LedgerDirection
    from apps.wallet.services import post_entry

    wallet = get_or_create_wallet(user)
    post_entry(wallet=wallet, amount=BONUS, entry_type=LedgerEntryType.REFERRAL_BONUS,
               direction=LedgerDirection.CREDIT, idempotency_key="bonus", funds=FundType.PROMO)

    with pytest.raises(ValidationFailed, match="cannot move PROMO"):
        post_entry(wallet=wallet, amount=BONUS, entry_type=LedgerEntryType.WITHDRAWAL,
                   direction=LedgerDirection.DEBIT, idempotency_key="cashout",
                   funds=FundType.PROMO)

    wallet.refresh_from_db()
    assert wallet.promo_balance == BONUS
    assert wallet.balance == Decimal("0.00")


def test_the_database_refuses_a_withdrawal_of_promotional_funds(user):
    """Even a writer that bypassed the service could not do it."""
    from django.db import IntegrityError, transaction

    wallet = get_or_create_wallet(user)
    with pytest.raises(IntegrityError), transaction.atomic():
        WalletLedgerEntry.objects.create(
            wallet=wallet, reference="VGH-TXN-PROMOOUT", sequence=1,
            idempotency_key="raw-withdrawal", entry_type=LedgerEntryType.WITHDRAWAL,
            direction="DEBIT", funds=FundType.PROMO, amount=BONUS,
            balance_before=BONUS, balance_after=Decimal("0.00"), currency="GHS",
        )


def test_promotional_credit_cannot_be_moved_to_another_user(user, other_user):
    """There is no transfer path at all - and the ledger has no way to express
    one, because every entry belongs to exactly one wallet."""
    from apps.wallet.services import post_entry

    wallet = get_or_create_wallet(user)
    post_entry(wallet=wallet, amount=BONUS, entry_type=LedgerEntryType.REFERRAL_BONUS,
               direction="CREDIT", idempotency_key="bonus", funds=FundType.PROMO)

    other = get_or_create_wallet(other_user)
    assert other.promo_balance == Decimal("0.00")
    assert not WalletLedgerEntry.objects.filter(wallet=other).exists()
    # No endpoint accepts a recipient.
    from django.urls import get_resolver

    paths = str(get_resolver().url_patterns)
    assert "transfer" not in paths and "send-money" not in paths


def test_a_bonus_does_not_earn_another_bonus(api, user, capture_token):
    """Promotional credit is not a payment, so it cannot seed a referral chain."""
    register(api, code=code_for(user).code)
    verify(api, capture_token)
    referred = User.objects.get(email=FRIEND)

    # The referred user now invites someone; their own bonus is irrelevant.
    their_code = code_for(referred).code
    register(api, email="kofi@example.com", code=their_code)

    chain = Referral.objects.get(referred_user__email="kofi@example.com")
    assert chain.status == ReferralStatus.PENDING
    assert promo_balance(referred) == BONUS  # the referrer earns nothing
    assert ReferralReward.objects.filter(user=referred).count() == 1
