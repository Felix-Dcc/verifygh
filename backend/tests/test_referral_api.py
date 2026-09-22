"""The referral endpoints: what they show, and what they refuse to show."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.referrals.models import Referral, ReferralReward, ReferralStatus
from apps.referrals.services import code_for

pytestmark = pytest.mark.django_db

ME = "/api/v1/referrals/me/"
STATS = "/api/v1/referrals/stats/"
HISTORY = "/api/v1/referrals/history/"
VALIDATE = "/api/v1/referrals/validate/"
PASSWORD = "Correct-Horse-Battery-1"


def make_referral(referrer, email, status=ReferralStatus.PENDING, reward=False):
    friend = User.objects.create_user(email=email, password=PASSWORD)
    referral = Referral.objects.create(referrer=referrer, referred_user=friend,
                                       code=code_for(referrer).code, status=status)
    if reward:
        ReferralReward.objects.create(referral=referral, user=friend,
                                      reference=f"VGH-REF-{email[:6].upper()}",
                                      amount=Decimal("5.00"))
    return referral


def test_my_referral_returns_a_code_and_a_working_link(user, auth):
    response = auth(user).get(ME)

    assert response.status_code == 200
    body = response.data
    assert body["code"] == code_for(user).code
    assert body["share_url"].endswith(f"/register?ref={body['code']}")
    assert body["bonus_amount"] == "5.00"
    assert body["enabled"] is True


def test_the_dashboard_counts_what_the_user_expects(user, auth):
    make_referral(user, "one@example.com", ReferralStatus.REWARDED, reward=True)
    make_referral(user, "two@example.com", ReferralStatus.REWARDED, reward=True)
    make_referral(user, "three@example.com", ReferralStatus.PENDING)
    make_referral(user, "four@example.com", ReferralStatus.REJECTED)

    stats = auth(user).get(STATS).data

    assert stats["successful"] == 2
    assert stats["pending"] == 1
    assert stats["rejected"] == 1
    assert stats["rewards_issued"] == "10.00"


def test_a_flagged_referral_reads_as_pending_to_the_referrer(user, auth):
    """Telling someone which fraud check caught them is a tutorial in evasion."""
    make_referral(user, "flagged@example.com", ReferralStatus.FRAUD_FLAGGED)

    stats = auth(user).get(STATS).data
    history = auth(user).get(HISTORY).data["results"]

    assert stats["pending"] == 1
    assert history[0]["status"] == "PENDING"
    assert "FRAUD" not in str(history)


def test_history_masks_the_invited_email_addresses(user, auth):
    make_referral(user, "kwabena@example.com", ReferralStatus.REWARDED, reward=True)

    history = auth(user).get(HISTORY).data["results"]

    assert history[0]["friend"] == "k***@example.com"
    assert "kwabena@example.com" not in str(history)


def test_history_never_includes_internal_identifiers(user, auth):
    referral = make_referral(user, "ids@example.com", ReferralStatus.REWARDED, reward=True)

    body = str(auth(user).get(HISTORY).data)

    assert str(referral.id) not in body
    assert str(referral.referred_user_id) not in body
    assert "staff_note" not in body and "risk" not in body


def test_one_user_cannot_read_another_users_referrals(user, other_user, auth):
    make_referral(user, "mine@example.com", ReferralStatus.REWARDED, reward=True)

    history = auth(other_user, "Correct-Horse-Battery-2").get(HISTORY).data["results"]
    stats = auth(other_user, "Correct-Horse-Battery-2").get(STATS).data

    assert history == []
    assert stats["successful"] == 0
    assert stats["rewards_issued"] == "0.00"


@pytest.mark.parametrize("url", [ME, STATS, HISTORY])
def test_referral_endpoints_require_a_session(api, url):
    assert api.get(url).status_code == 401


def test_validate_confirms_a_real_code_without_naming_its_owner(api, user):
    response = api.post(VALIDATE, {"code": code_for(user).code}, format="json")

    assert response.status_code == 200
    assert response.data["valid"] is True
    assert response.data["bonus_amount"] == "5.00"
    body = str(response.data)
    assert user.email not in body and str(user.id) not in body


def test_validate_rejects_an_unknown_code_without_an_error(api):
    response = api.post(VALIDATE, {"code": "VGHNOPE9"}, format="json")

    assert response.status_code == 200
    assert response.data["valid"] is False


def test_validate_does_not_leak_suspended_accounts(api, user):
    code = code_for(user).code
    User.objects.filter(pk=user.pk).update(is_suspended=True)

    assert api.post(VALIDATE, {"code": code}, format="json").data["valid"] is False


def test_no_endpoint_lets_a_client_award_itself_credit(user, auth, api):
    """There is no claim endpoint, and nothing accepts an amount."""
    client = auth(user)
    for url in (ME, STATS, HISTORY, "/api/v1/referrals/claim/", "/api/v1/referrals/reward/"):
        response = client.post(url, {"amount": "500.00", "code": "VGHMINE1"}, format="json")
        assert response.status_code in (404, 405), url

    from apps.wallet.services import get_or_create_wallet

    assert get_or_create_wallet(user).promo_balance == Decimal("0.00")
