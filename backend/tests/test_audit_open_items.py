"""Regression tests for the open items of the October 2026 audit (docs/AUDIT-2026-10.md).

A-09  logout and refresh accepted cross-site form posts
A-11  the promotional/cash split of a purchase was read without the wallet lock
A-10  a rental refunded for want of an answer was never followed up with the provider
A-14  the referral funnel left invited users' rentals out of buyers and revenue
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

import pytest
from django.db import transaction

from apps.wallet import services as wallet_services

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
LOGOUT = "/api/v1/auth/logout/"
REFRESH = "/api/v1/auth/refresh/"


# ---------------------------------------------------------------------------
# A-09: refresh and logout refuse cross-site form posts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [LOGOUT, REFRESH])
@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded",
                                          "multipart/form-data; boundary=x", "text/plain"])
def test_a_cross_site_form_post_cannot_sign_the_visitor_out_or_rotate_them(
        user, auth, url, content_type):
    client = auth(user)
    response = client.post(url, "", content_type=content_type)

    assert response.status_code == 415
    assert "vgh_access" not in response.cookies
    # The session the form tried to end or rotate still works.
    assert client.get(ME).status_code == 200


def test_the_frontends_json_sign_out_still_works(user, auth):
    client = auth(user)
    response = client.post(LOGOUT, {}, format="json")

    assert response.status_code == 200
    assert client.get(ME).status_code == 401


def test_the_frontends_json_refresh_still_works(user, auth):
    client = auth(user)
    response = client.post(REFRESH, "{}", content_type="application/json")

    assert response.status_code == 200
    assert response.cookies["vgh_access"].value


# ---------------------------------------------------------------------------
# A-11: the promo/cash split is read under the wallet lock
# ---------------------------------------------------------------------------


def _record_order(monkeypatch):
    """Wrap the wallet lock and the split so their order of calls is recorded."""
    calls = []
    real_lock, real_split = wallet_services._lock, wallet_services.split_charge

    def lock(wallet_id):
        calls.append("lock")
        return real_lock(wallet_id)

    def split(wallet, amount):
        calls.append("split")
        return real_split(wallet, amount)

    monkeypatch.setattr(wallet_services, "_lock", lock)
    monkeypatch.setattr(wallet_services, "split_charge", split)
    return calls


def test_a_purchase_locks_the_wallet_before_splitting_promo_and_cash(
        user, funded_wallet, monkeypatch):
    wallet = funded_wallet(user, "20.00")
    calls = _record_order(monkeypatch)

    with transaction.atomic():
        wallet_services.charge_order(wallet=wallet, amount=Decimal("5.00"), order_id=wallet.pk,
                                     order_reference="VGH-SPLIT", service_name="Split check")

    assert calls[:2] == ["lock", "split"]


def test_the_split_uses_the_locked_balance_not_a_stale_one(user, funded_wallet):
    """Promo credit spent elsewhere after the caller loaded the wallet: the
    split must see the row as it is now, and charge cash instead."""
    from apps.wallet.models import FundType, LedgerDirection, LedgerEntryType

    wallet = funded_wallet(user, "20.00")
    wallet_services.credit_referral_bonus(wallet=wallet, amount=Decimal("5.00"),
                                          idempotency_key="bonus", referral_id="r",
                                          reward_reference="R1")
    stale = type(wallet).objects.get(pk=wallet.pk)
    assert stale.promo_balance == Decimal("5.00")
    wallet_services.post_entry(wallet=wallet, amount=Decimal("5.00"),
                               entry_type=LedgerEntryType.PURCHASE,
                               direction=LedgerDirection.DEBIT, idempotency_key="elsewhere",
                               funds=FundType.PROMO)

    with transaction.atomic(), mock.patch.object(type(stale), "refresh_from_db"):
        # refresh_from_db is disabled: only the lock may bring the row up to date.
        charge = wallet_services.charge_order(
            wallet=stale, amount=Decimal("5.00"), order_id=wallet.pk,
            order_reference="VGH-STALE", service_name="Stale check")

    assert charge.promo == Decimal("0.00")
    assert charge.cash == Decimal("5.00")


# ---------------------------------------------------------------------------
# A-14: the referral funnel counts rentals
# ---------------------------------------------------------------------------


def test_the_referral_funnel_counts_an_invited_users_rental_and_extension(
        user, other_user, admin_user, auth, catalog, funded_wallet,
        django_capture_on_commit_callbacks):
    from apps.referrals.models import Referral
    from apps.referrals.services import code_for
    from apps.rentals.models import Rental, RentalExtension
    from apps.verification import mock as verification_mock

    Referral.objects.create(referrer=user, referred_user=other_user, code=code_for(user).code)
    funded_wallet(other_user, "400.00")
    verification_mock.force_rental_mode("QUIET")
    friend = auth(other_user, "Correct-Horse-Battery-2")
    with django_capture_on_commit_callbacks(execute=True):
        reference = friend.post("/api/v1/rentals/", {"service": "whatsapp", "days": 30},
                                format="json").data["reference"]
    friend.post(f"/api/v1/rentals/{reference}/extend/", {"days": 7}, format="json")
    rental = Rental.objects.get(reference=reference)
    extension = RentalExtension.objects.get()

    data = auth(admin_user, "Correct-Horse-Battery-3").get(
        "/api/v1/admin/referrals-analytics/").data

    assert data["invited_buyers"] == 1
    assert data["invited_rentals"] == 1
    assert data["invited_orders"] == 0
    assert Decimal(data["invited_revenue"]) == rental.price + extension.price
    assert Decimal(data["invited_cash_revenue"]) == rental.cash_amount + extension.cash_amount
    by_product = data["invited_revenue_by_product"]
    assert Decimal(by_product["rentals"]["revenue"]) == rental.price
    assert Decimal(by_product["extensions"]["revenue"]) == extension.price
    assert Decimal(by_product["orders"]["revenue"]) == 0


# ---------------------------------------------------------------------------
# A-10: purchases refunded without an answer are followed up
# ---------------------------------------------------------------------------


def _rent_and_give_up(user, auth, funded_wallet, django_capture_on_commit_callbacks):
    """A rental whose sale the provider is still processing when we give up."""
    from django.core.cache import cache
    from django.utils import timezone

    from apps.rentals.models import Rental, RentalStatus
    from apps.rentals.tasks import process_rentals
    from apps.verification import mock as verification_mock

    funded_wallet(user, "200.00")
    verification_mock.force_rental_mode("PENDING")
    with django_capture_on_commit_callbacks(execute=True):
        reference = auth(user).post("/api/v1/rentals/", {"service": "whatsapp", "days": 30},
                                    format="json").data["reference"]
    rental = Rental.objects.get(reference=reference)
    assert rental.status == RentalStatus.PENDING and rental.provider_sale_id

    key = f"{verification_mock.RENTAL_PREFIX}{rental.provider_sale_id}"
    state = cache.get(key)
    state["pending_reads"] = 99
    cache.set(key, state)
    Rental.objects.filter(pk=rental.pk).update(
        created_at=timezone.now() - timezone.timedelta(minutes=45))
    verification_mock.force_rental_mode("QUIET")
    process_rentals()
    rental.refresh_from_db()
    assert rental.status == RentalStatus.FAILED
    return rental, key


def _sale_settles(key, **changes):
    from django.core.cache import cache

    state = cache.get(key)
    state.update({"pending_reads": 0, **changes})
    cache.set(key, state)


def _sale_state(rental):
    return rental.metadata["reconcile"]["sale"][rental.provider_sale_id]["state"]


def _capture_alerts(monkeypatch):
    from apps.rentals import services as rental_services

    alerts = []
    monkeypatch.setattr(rental_services, "_reconcile_alert",
                        lambda rental, title, body: alerts.append(title))
    return alerts


def test_a_given_up_rental_is_flagged_for_follow_up(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks):
    rental, _ = _rent_and_give_up(user, auth, funded_wallet,
                                  django_capture_on_commit_callbacks)

    assert rental.metadata["reconcile_pending"] is True
    assert _sale_state(rental) == "pending"


def test_a_sale_that_went_through_after_all_is_refunded_by_the_provider(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks):
    from django.core.cache import cache

    from apps.rentals.tasks import reconcile_given_up_rentals
    from apps.wallet.services import get_or_create_wallet

    rental, key = _rent_and_give_up(user, auth, funded_wallet,
                                    django_capture_on_commit_callbacks)
    refunded_balance = get_or_create_wallet(user).balance
    _sale_settles(key)

    assert reconcile_given_up_rentals() == {"checked": 1}

    rental.refresh_from_db()
    assert _sale_state(rental) == "recovered"
    assert rental.metadata["reconcile_pending"] is False
    assert cache.get(key)["state"] == "REFUNDED"  # our money back from the provider
    # The customer's refund stands; nothing was charged or credited again.
    assert get_or_create_wallet(user).balance == refunded_balance
    assert reconcile_given_up_rentals() == {"checked": 0}


def test_staff_are_told_when_the_provider_will_not_refund_it(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks, monkeypatch):
    from apps.rentals.tasks import reconcile_given_up_rentals

    rental, key = _rent_and_give_up(user, auth, funded_wallet,
                                    django_capture_on_commit_callbacks)
    _sale_settles(key, refundable=False)
    alerts = _capture_alerts(monkeypatch)

    reconcile_given_up_rentals()

    rental.refresh_from_db()
    assert _sale_state(rental) == "unrecovered"
    assert alerts == [f"Rental {rental.reference}: provider kept the money"]


def test_a_sale_the_provider_never_completed_needs_nothing(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks, monkeypatch):
    from apps.rentals.tasks import reconcile_given_up_rentals

    rental, key = _rent_and_give_up(user, auth, funded_wallet,
                                    django_capture_on_commit_callbacks)
    _sale_settles(key, state="REFUNDED")
    alerts = _capture_alerts(monkeypatch)

    reconcile_given_up_rentals()

    rental.refresh_from_db()
    assert _sale_state(rental) == "nothing_bought"
    assert alerts == []


def test_a_sale_still_unclear_after_48_hours_goes_to_staff(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks, monkeypatch):
    from django.utils import timezone

    from apps.rentals.models import Rental
    from apps.rentals.tasks import reconcile_given_up_rentals

    rental, _ = _rent_and_give_up(user, auth, funded_wallet, django_capture_on_commit_callbacks)
    reconcile_given_up_rentals()  # still processing: stays pending
    rental.refresh_from_db()
    assert rental.metadata["reconcile_pending"] is True

    meta = rental.metadata
    meta["reconcile"]["sale"][rental.provider_sale_id]["since"] = (
        timezone.now() - timezone.timedelta(hours=49)).isoformat()
    Rental.objects.filter(pk=rental.pk).update(metadata=meta)
    alerts = _capture_alerts(monkeypatch)

    reconcile_given_up_rentals()

    rental.refresh_from_db()
    assert _sale_state(rental) == "unresolved"
    assert alerts == [f"Rental {rental.reference}: sale still unclear"]


def test_an_extension_refunded_blind_is_reported_if_the_days_were_added(
        user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks, monkeypatch):
    from apps.common.errors import ProviderError
    from apps.rentals import services as rental_services
    from apps.rentals.models import ExtensionStatus, Rental, RentalExtension
    from apps.rentals.tasks import reconcile_given_up_rentals
    from apps.verification import mock as verification_mock

    funded_wallet(user, "400.00")
    verification_mock.force_rental_mode("QUIET")
    client = auth(user)
    with django_capture_on_commit_callbacks(execute=True):
        reference = client.post("/api/v1/rentals/", {"service": "whatsapp", "days": 30},
                                format="json").data["reference"]
    client.post(f"/api/v1/rentals/{reference}/extend/", {"days": 7}, format="json")
    extension = RentalExtension.objects.get()
    assert extension.status == ExtensionStatus.COMPLETED
    # Pretend its answer was lost: back to PENDING, the rental's end not moved.
    RentalExtension.objects.filter(pk=extension.pk).update(status=ExtensionStatus.PENDING)
    rental = Rental.objects.get(reference=reference)
    Rental.objects.filter(pk=rental.pk).update(ends_at=extension.previous_ends_at)
    extension.refresh_from_db()

    real_get = verification_mock.MockVerificationProvider.get_rental

    def unreachable(self, provider_rental_id):
        raise ProviderError("The verification provider did not respond in time.")

    monkeypatch.setattr(verification_mock.MockVerificationProvider, "get_rental", unreachable)
    rental_services.settle_extension(extension, give_up=True)
    extension.refresh_from_db()
    assert extension.status == ExtensionStatus.FAILED  # customer refunded

    monkeypatch.setattr(verification_mock.MockVerificationProvider, "get_rental", real_get)
    alerts = _capture_alerts(monkeypatch)
    reconcile_given_up_rentals()

    rental.refresh_from_db()
    entry = rental.metadata["reconcile"]["extensions"][str(extension.pk)]
    assert entry["state"] == "applied_after_refund"
    assert alerts == [f"Rental {rental.reference}: extension made after its refund"]
