"""A-13: what was refunded lives on the order, so no report can forget it.

A refund on a delivered order leaves its status as it was. Revenue used to be
netted by joining to Refund in one helper (A-01); any new report that summed
`price` alone would have brought the bug back. `Order.refunded_amount` is set
with the refund, backfilled from history, bounded by the database, and is
what the earnings helper reads.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.orders.models import Order, OrderStatus, Refund, RefundReason
from apps.orders.services import issue_refund, poll_order
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "Correct-Horse-Battery-3"


@pytest.fixture
def delivered(user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks):
    funded_wallet(user, "200.00")
    verification_mock.force_scenario("HAPPY")
    with django_capture_on_commit_callbacks(execute=True):
        reference = auth(user).post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                                    format="json").data["reference"]
    order = Order.objects.get(reference=reference)
    verification_mock.fast_forward(order.provider_order_id, 30)
    order = poll_order(order)
    assert order.status == OrderStatus.CODE_RECEIVED
    return order


def test_a_partial_refund_is_recorded_on_the_order(delivered, admin_user):
    issue_refund(delivered, reason=RefundReason.ADMIN_GOODWILL, amount=Decimal("1.00"),
                 actor=admin_user, automatic=False)
    delivered.refresh_from_db()

    assert delivered.refunded_amount == Decimal("1.00")
    assert delivered.status == OrderStatus.CODE_RECEIVED


def test_a_full_refund_records_the_whole_price(user, auth, catalog, funded_wallet,
                                               django_capture_on_commit_callbacks):
    funded_wallet(user, "200.00")
    verification_mock.force_scenario("PROVIDER_ERR")
    with django_capture_on_commit_callbacks(execute=True):
        reference = auth(user).post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                                    format="json").data["reference"]
    order = Order.objects.get(reference=reference)

    assert order.status == OrderStatus.REFUNDED
    assert order.refunded_amount == order.price


def test_a_refund_is_never_more_than_the_price(delivered, admin_user):
    issue_refund(delivered, reason=RefundReason.ADMIN_GOODWILL,
                 amount=Decimal(delivered.price) + Decimal("5.00"), actor=admin_user,
                 automatic=False)
    delivered.refresh_from_db()

    assert delivered.refunded_amount == delivered.price
    assert Refund.objects.get(order=delivered).amount == delivered.price


def test_the_database_refuses_a_refund_above_the_price(delivered):
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.filter(pk=delivered.pk).update(
            refunded_amount=Decimal(delivered.price) + Decimal("0.01"))


def test_reports_read_the_column(delivered, admin_user, auth):
    """Revenue follows refunded_amount even with no Refund row to join to."""
    Order.objects.filter(pk=delivered.pk).update(refunded_amount=Decimal("2.00"))

    revenue = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["revenue"]

    assert Decimal(revenue["by_product"]["orders"]["revenue"]) == \
        Decimal(delivered.price) - Decimal("2.00")


def test_admins_see_the_refunded_amount(delivered, admin_user, auth):
    issue_refund(delivered, reason=RefundReason.ADMIN_GOODWILL, amount=Decimal("1.50"),
                 actor=admin_user, automatic=False)

    row = auth(admin_user, ADMIN_PASSWORD).get(
        f"/api/v1/admin/orders/{delivered.reference}/").data

    assert row["refunded_amount"] == "1.50"


def test_the_migration_backfills_past_refunds(delivered, admin_user):
    import importlib

    from django.apps import apps as registry_apps

    issue_refund(delivered, reason=RefundReason.ADMIN_GOODWILL, amount=Decimal("1.25"),
                 actor=admin_user, automatic=False)
    Order.objects.filter(pk=delivered.pk).update(refunded_amount=Decimal("0.00"))

    migration = importlib.import_module("apps.orders.migrations.0007_order_refunded_amount")
    migration.backfill_refunded_amount(registry_apps, None)

    delivered.refresh_from_db()
    assert delivered.refunded_amount == Decimal("1.25")
