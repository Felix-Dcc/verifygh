"""Referral management: who may act, and what every action leaves behind.

Staff can review, approve, reject, flag and reverse. None of those is a
balance edit: each one goes through the referral service, which goes through
the ledger, and each writes an AdminAction with a reason.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.referrals.models import (
    Referral,
    ReferralProgram,
    ReferralReward,
    ReferralStatus,
    RewardStatus,
)
from apps.referrals.services import code_for, issue_reward
from apps.wallet.models import FundType, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

LIST = "/api/v1/admin/referrals/"
ANALYTICS = "/api/v1/admin/referrals-analytics/"
PROGRAM = "/api/v1/admin/referral-program/"
PASSWORD = "Correct-Horse-Battery-9"
REASON = {"reason": "Checked with the customer by phone."}


@pytest.fixture
def staff(db):
    def _make(role: str) -> User:
        return User.objects.create_user(email=f"{role.lower()}@staff.test", password=PASSWORD,
                                        role=role, is_email_verified=True)
    return _make


@pytest.fixture
def signed_in(api):
    def _sign_in(account: User):
        response = api.post("/api/v1/auth/login/",
                            {"email": account.email, "password": PASSWORD}, format="json")
        assert response.status_code == 200, response.data
        api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
        return api
    return _sign_in


@pytest.fixture
def referral(user):
    friend = User.objects.create_user(email="friend@example.com", password=PASSWORD,
                                      is_email_verified=True)
    return Referral.objects.create(referrer=user, referred_user=friend,
                                   code=code_for(user).code,
                                   status=ReferralStatus.FRAUD_FLAGGED)


def test_support_can_review_referrals_but_not_decide_them(staff, signed_in, referral):
    client = signed_in(staff(Role.SUPPORT))

    assert client.get(LIST).status_code == 200
    assert client.get(ANALYTICS).status_code == 200
    for action in ("approve", "reject", "flag", "reverse-reward"):
        response = client.post(f"{LIST}{referral.id}/{action}/", REASON, format="json")
        assert response.status_code == 403, action

    referral.refresh_from_db()
    assert referral.status == ReferralStatus.FRAUD_FLAGGED
    assert not AdminAction.objects.exists()


def test_a_normal_user_cannot_reach_referral_management(user, auth, referral):
    client = auth(user)
    assert client.get(LIST).status_code == 403
    assert client.post(f"{LIST}{referral.id}/approve/", REASON, format="json").status_code == 403


def test_an_admin_can_release_a_held_referral_and_it_is_audited(staff, signed_in, referral):
    admin = staff(Role.ADMIN)
    response = signed_in(admin).post(f"{LIST}{referral.id}/approve/", REASON, format="json")

    assert response.status_code == 200
    referral.refresh_from_db()
    assert referral.status == ReferralStatus.REWARDED
    assert get_or_create_wallet(referral.referred_user).promo_balance == Decimal("5.00")

    record = AdminAction.objects.get(action="REFERRAL_APPROVE")
    assert record.admin_id == admin.pk
    assert record.reason == REASON["reason"]
    assert record.after["amount"] == "5.00"


def test_approving_twice_cannot_pay_twice(staff, signed_in, referral):
    client = signed_in(staff(Role.ADMIN))
    first = client.post(f"{LIST}{referral.id}/approve/", REASON, format="json")
    second = client.post(f"{LIST}{referral.id}/approve/", REASON, format="json")

    assert first.status_code == 200
    assert second.status_code == 409
    assert ReferralReward.objects.filter(referral=referral).count() == 1
    assert get_or_create_wallet(referral.referred_user).promo_balance == Decimal("5.00")


def test_rejecting_a_referral_records_the_staff_reason_only_for_staff(staff, signed_in,
                                                                     referral):
    response = signed_in(staff(Role.ADMIN)).post(f"{LIST}{referral.id}/reject/",
                                                 {"reason": "Duplicate household account."},
                                                 format="json")

    assert response.status_code == 200
    referral.refresh_from_db()
    assert referral.status == ReferralStatus.REJECTED
    assert referral.staff_note == "Duplicate household account."
    # The customer-facing reason says nothing about why.
    assert "Duplicate" not in referral.reason
    assert AdminAction.objects.filter(action="REFERRAL_REJECT").count() == 1


def test_a_reason_is_required_for_every_decision(staff, signed_in, referral):
    client = signed_in(staff(Role.ADMIN))
    for action in ("approve", "reject", "flag"):
        assert client.post(f"{LIST}{referral.id}/{action}/", {}, format="json").status_code == 400
    assert not AdminAction.objects.exists()


def test_reversing_a_reward_needs_the_wallet_permission(staff, signed_in, referral):
    issue_reward(referral, force=True)

    admin = signed_in(staff(Role.ADMIN))
    assert admin.post(f"{LIST}{referral.id}/reverse-reward/", REASON,
                      format="json").status_code == 403
    assert get_or_create_wallet(referral.referred_user).promo_balance == Decimal("5.00")

    response = signed_in(staff(Role.SUPER_ADMIN)).post(f"{LIST}{referral.id}/reverse-reward/",
                                                       REASON, format="json")
    assert response.status_code == 200

    wallet = get_or_create_wallet(referral.referred_user)
    assert wallet.promo_balance == Decimal("0.00")
    assert wallet.balance == Decimal("0.00")  # nothing was converted to cash
    reward = ReferralReward.objects.get(referral=referral)
    assert reward.status == RewardStatus.REVERSED
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.REVERSAL, funds=FundType.PROMO).count() == 1
    assert AdminAction.objects.filter(action="REFERRAL_REWARD_REVERSE").count() == 1
    assert verify_wallet_integrity(wallet)["ok"]


def test_reversing_already_spent_credit_never_touches_cash(staff, signed_in, referral,
                                                           catalog, funded_wallet):
    """If the user already spent the bonus, we take what is left - not their money."""
    from apps.orders.services import create_order

    issue_reward(referral, force=True)
    friend = referral.referred_user
    User.objects.filter(pk=friend.pk).update(
        accepted_terms_version=settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    )
    friend.refresh_from_db()
    funded_wallet(friend, "100.00")
    create_order(user=friend, service_slug="instagram", country_code="US",
                 idempotency_key="spent-it")
    spent_cash = get_or_create_wallet(friend).balance

    response = signed_in(staff(Role.SUPER_ADMIN)).post(f"{LIST}{referral.id}/reverse-reward/",
                                                       REASON, format="json")

    assert response.status_code == 200
    wallet = get_or_create_wallet(friend)
    assert wallet.promo_balance == Decimal("0.00")
    assert wallet.balance == spent_cash  # their cash is untouched
    assert verify_wallet_integrity(wallet)["ok"]


def test_the_admin_list_filters_by_status(staff, signed_in, referral, user):
    other = User.objects.create_user(email="rewarded@example.com", password=PASSWORD)
    Referral.objects.create(referrer=user, referred_user=other, code=code_for(user).code,
                            status=ReferralStatus.REWARDED)
    client = signed_in(staff(Role.SUPPORT))

    assert len(client.get(f"{LIST}?status=FRAUD_FLAGGED").data["results"]) == 1
    assert len(client.get(f"{LIST}?status=REWARDED").data["results"]) == 1
    assert len(client.get(f"{LIST}?status=ALL").data["results"]) == 2
    assert len(client.get(f"{LIST}?search=rewarded@example.com").data["results"]) == 1


def test_staff_see_the_risk_flags_and_the_reward_trail(staff, signed_in, referral):
    from apps.referrals.models import ReferralRiskFlag, RiskKind, RiskLevel

    ReferralRiskFlag.objects.create(referral=referral, kind=RiskKind.SHARED_DEVICE,
                                    level=RiskLevel.HIGH, detail="Same device.", blocking=True)
    issue_reward(referral, force=True)

    detail = signed_in(staff(Role.SUPPORT)).get(f"{LIST}{referral.id}/").data

    assert detail["risk_flags"][0]["kind"] == RiskKind.SHARED_DEVICE
    assert detail["reward"]["amount"] == "5.00"
    assert detail["reward"]["ledger_entry_id"]
    assert detail["referred_email"] == "friend@example.com"  # staff see the real address


def test_analytics_never_count_rejected_or_fraudulent_signups_as_acquisitions(staff, signed_in,
                                                                             user):
    for index, status in enumerate(
        [ReferralStatus.REWARDED, ReferralStatus.REWARDED, ReferralStatus.REJECTED,
         ReferralStatus.FRAUD_FLAGGED, ReferralStatus.PENDING]
    ):
        friend = User.objects.create_user(email=f"a{index}@example.com", password=PASSWORD)
        referral = Referral.objects.create(referrer=user, referred_user=friend,
                                           code=code_for(user).code, status=status)
        if status == ReferralStatus.REWARDED:
            ReferralReward.objects.create(referral=referral, user=friend,
                                          reference=f"VGH-REF-ANALY{index}",
                                          amount=Decimal("5.00"))

    data = signed_in(staff(Role.SUPPORT)).get(ANALYTICS).data

    assert data["registrations"] == 5
    assert data["rewarded"] == 2
    assert data["rejected"] == 1
    assert data["fraud_flagged"] == 1
    assert data["promotional_credit_issued"] == "10.00"
    assert data["average_acquisition_cost"] == "5.00"
    assert data["conversion_rate"] == 40.0


def test_only_a_super_admin_can_change_the_programme(staff, signed_in):
    admin = signed_in(staff(Role.ADMIN))
    assert admin.get(PROGRAM).status_code == 200
    assert admin.patch(PROGRAM, {"signup_bonus": "50.00"}, format="json").status_code == 403

    response = signed_in(staff(Role.SUPER_ADMIN)).patch(
        PROGRAM, {"signup_bonus": "7.50", "max_monthly_successful_referrals": 5,
                  "reason": "Q4 campaign"}, format="json")

    assert response.status_code == 200
    program = ReferralProgram.load()
    assert program.signup_bonus == Decimal("7.50")
    assert program.max_monthly_successful_referrals == 5
    record = AdminAction.objects.get(action="REFERRAL_PROGRAM_UPDATE")
    assert record.before["signup_bonus"] == "5.00"
    assert record.after["signup_bonus"] == "7.50"


def test_pausing_the_programme_stops_new_attributions(staff, signed_in):
    signed_in(staff(Role.SUPER_ADMIN)).patch(PROGRAM, {"is_enabled": False, "reason": "Pause"},
                                             format="json")

    assert ReferralProgram.load().is_enabled is False


def test_no_admin_endpoint_can_set_a_balance_directly(staff, signed_in, referral):
    """Referral management issues credit through the ledger or not at all."""
    client = signed_in(staff(Role.SUPER_ADMIN))
    response = client.post(f"{LIST}{referral.id}/approve/",
                           {**REASON, "amount": "500.00", "promo_balance": "500.00"},
                           format="json")

    assert response.status_code == 200
    assert get_or_create_wallet(referral.referred_user).promo_balance == Decimal("5.00")
