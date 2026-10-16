"""Regression tests for the open items of the October 2026 audit (docs/AUDIT-2026-10.md).

A-09  logout and refresh accepted cross-site form posts
A-11  the promotional/cash split of a purchase was read without the wallet lock
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
