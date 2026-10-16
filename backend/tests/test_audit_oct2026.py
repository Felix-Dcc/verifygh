"""Regression tests for the October 2026 audit (docs/AUDIT-2026-10.md).

A-01  a refund on a delivered order stayed in revenue (dashboard, charts, funding)
A-02  the Refunded tile left out rental and extension refunds
A-03  SUPPORT could read provider cost, FX and profit, which are PRICING_VIEW's
A-04  popular services counted failed and refunded orders as revenue
A-05  sign-in accepted cross-site form posts (login CSRF)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderStatus, RefundReason
from apps.orders.services import complete_order, issue_refund, poll_order
from apps.rentals.models import Rental, RentalStatus
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "Correct-Horse-Battery-3"
SUPPORT_PASSWORD = "Correct-Horse-Battery-4"
#: The mock rental price for WhatsApp, 30 days (see tests/test_rentals.py).
WHATSAPP_30 = Decimal("81.00")

_capture = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture
    _capture = django_capture_on_commit_callbacks
    yield
    _capture = None


def _delivered_order(client) -> Order:
    """Buy a number and receive its code, through the real endpoints."""
    verification_mock.force_scenario("HAPPY")
    with _capture(execute=True):
        response = client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                               format="json")
    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])
    verification_mock.fast_forward(order.provider_order_id, 30)
    order = poll_order(order)
    assert order.status == OrderStatus.CODE_RECEIVED
    return order


def _cost(order: Order) -> Decimal:
    return (Decimal(order.provider_cost) * Decimal(order.exchange_rate)).quantize(Decimal("0.01"))


def _rent(client, mode=None):
    verification_mock.force_rental_mode(mode or "QUIET")
    with _capture(execute=True):
        return client.post("/api/v1/rentals/", {"service": "whatsapp", "days": 30},
                           format="json")


# ---------------------------------------------------------------------------
# A-01: revenue is net of refunds on delivered orders
# ---------------------------------------------------------------------------


def test_a_goodwill_refund_on_a_delivered_order_comes_off_revenue_everywhere(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    order = _delivered_order(auth(user))
    price = Decimal(order.price)

    staff = auth(admin_user, ADMIN_PASSWORD)
    response = staff.post(f"/api/v1/admin/orders/{order.reference}/refund/",
                          {"amount": "1.00", "reason": "Code arrived late"}, format="json")
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    # The order keeps its delivered status: that is why revenue has to net it.
    assert order.status == OrderStatus.CODE_RECEIVED

    revenue = staff.get("/api/v1/admin/overview/").data["revenue"]
    assert Decimal(revenue["total"]) == price - Decimal("1.00")
    assert Decimal(revenue["by_product"]["orders"]["revenue"]) == price - Decimal("1.00")
    # We still paid the provider for the number.
    assert Decimal(revenue["provider_cost"]) == _cost(order)

    charts = staff.get("/api/v1/admin/charts/?days=7").data
    assert Decimal(charts["totals"]["revenue"]) == price - Decimal("1.00")
    assert sum(Decimal(row["revenue"]) for row in charts["revenue"]) == price - Decimal("1.00")

    flow = staff.get("/api/v1/admin/funding/").data["cash_flow"]
    assert Decimal(flow["earnings_all_time"]["revenue"]) == price - Decimal("1.00")


def test_an_upheld_report_on_a_completed_order_leaves_no_revenue(
        user, admin_user, auth, catalog, funded_wallet):
    """A full refund of a COMPLETED order, which keeps its status."""
    funded_wallet(user, "200.00")
    order = complete_order(_delivered_order(auth(user)))
    issue_refund(order, reason=RefundReason.ADMIN_GOODWILL, actor=admin_user,
                 automatic=False, override_delivered=True)
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED

    revenue = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["revenue"]
    assert Decimal(revenue["total"]) == Decimal("0.00")
    # Unrecovered provider cost is a loss, and the margin says so.
    assert Decimal(revenue["provider_cost"]) == _cost(order)
    assert Decimal(revenue["gross_margin"]) == -_cost(order)


def test_provider_cost_comes_off_when_the_provider_refunds_us(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    order = complete_order(_delivered_order(auth(user)))
    issue_refund(order, reason=RefundReason.ADMIN_GOODWILL, actor=admin_user,
                 automatic=False, override_delivered=True, provider_refunded=True)

    revenue = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["revenue"]
    assert Decimal(revenue["total"]) == Decimal("0.00")
    assert Decimal(revenue["provider_cost"]) == Decimal("0.00")


def test_a_delivered_order_without_a_refund_still_counts_in_full(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    order = _delivered_order(auth(user))

    revenue = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["revenue"]
    assert Decimal(revenue["total"]) == Decimal(order.price)
    assert Decimal(revenue["provider_cost"]) == _cost(order)


# ---------------------------------------------------------------------------
# A-02: the Refunded tile includes rentals
# ---------------------------------------------------------------------------


def test_the_refunded_tile_counts_a_failed_rentals_refund(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "400.00")
    response = _rent(auth(user), mode="REFUSE")
    rental = Rental.objects.get(reference=response.data["reference"])
    assert rental.status == RentalStatus.FAILED
    assert Decimal(rental.refunded_amount) == WHATSAPP_30

    refunds = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["refunds"]
    assert Decimal(refunds["total"]) == WHATSAPP_30
    assert refunds["count"] == 1
    assert refunds["by_product"]["rentals"] == {"total": "81.00", "count": 1}
    assert refunds["by_product"]["orders"]["count"] == 0


def test_the_refunded_tile_adds_order_and_rental_refunds(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "400.00")
    client = auth(user)
    order = _delivered_order(client)
    _rent(client, mode="REFUSE")
    issue_refund(order, reason=RefundReason.ADMIN_GOODWILL, amount=Decimal("2.00"),
                 actor=admin_user, automatic=False)

    refunds = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/overview/").data["refunds"]
    assert Decimal(refunds["total"]) == WHATSAPP_30 + Decimal("2.00")
    assert refunds["count"] == 2


# ---------------------------------------------------------------------------
# A-03: provider cost and profit are PRICING_VIEW's
# ---------------------------------------------------------------------------


def test_support_sees_revenue_but_not_cost_or_profit_on_the_dashboard(
        user, support_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    order = _delivered_order(auth(user))
    support = auth(support_user, SUPPORT_PASSWORD)

    revenue = support.get("/api/v1/admin/overview/").data["revenue"]
    assert Decimal(revenue["total"]) == Decimal(order.price)
    assert revenue["provider_cost"] is None
    assert revenue["gross_margin"] is None
    assert revenue["margin_percent"] is None
    assert all(part["provider_cost"] is None for part in revenue["by_product"].values())

    charts = support.get("/api/v1/admin/charts/?days=7").data
    assert Decimal(charts["totals"]["revenue"]) == Decimal(order.price)
    for row in [*charts["series"], charts["totals"], charts["previous_totals"]]:
        assert row["cost"] is None
        assert row["profit"] is None


def test_support_sees_no_cost_on_orders_or_rentals(
        user, support_user, auth, catalog, funded_wallet):
    funded_wallet(user, "400.00")
    client = auth(user)
    order = _delivered_order(client)
    rental = Rental.objects.get(reference=_rent(client).data["reference"])
    support = auth(support_user, SUPPORT_PASSWORD)

    listed = support.get("/api/v1/admin/orders/").data["results"][0]
    detail = support.get(f"/api/v1/admin/orders/{order.reference}/").data
    for row in (listed, detail):
        assert row["reference"] == order.reference
        assert row["price"] == str(order.price)
        for field in ("provider_cost", "provider_currency", "exchange_rate", "price_breakdown"):
            assert row[field] is None, field

    by_user = support.get(f"/api/v1/admin/users/{user.id}/orders/").data[0]
    assert by_user["provider_cost"] is None

    rental_row = support.get(f"/api/v1/admin/rentals/{rental.reference}/").data
    assert rental_row["price"] == str(rental.price)
    for field in ("provider_cost", "provider_currency", "exchange_rate"):
        assert rental_row[field] is None, field


def test_admins_still_see_cost_and_profit(user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "400.00")
    client = auth(user)
    order = _delivered_order(client)
    rental = Rental.objects.get(reference=_rent(client).data["reference"])
    staff = auth(admin_user, ADMIN_PASSWORD)

    detail = staff.get(f"/api/v1/admin/orders/{order.reference}/").data
    assert Decimal(detail["provider_cost"]) == Decimal(order.provider_cost)
    assert detail["price_breakdown"]
    assert Decimal(staff.get(f"/api/v1/admin/rentals/{rental.reference}/")
                   .data["provider_cost"]) == Decimal(rental.provider_cost)
    assert staff.get("/api/v1/admin/overview/").data["revenue"]["gross_margin"] is not None
    assert staff.get("/api/v1/admin/charts/?days=7").data["totals"]["profit"] is not None


# ---------------------------------------------------------------------------
# A-04: popular services count earned revenue only
# ---------------------------------------------------------------------------


def test_popular_services_revenue_leaves_out_failed_orders(
        user, admin_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    delivered = _delivered_order(client)
    verification_mock.force_scenario("PROVIDER_ERR")
    with _capture(execute=True):
        client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                    format="json")
    assert Order.objects.filter(status=OrderStatus.REFUNDED).count() == 1

    charts = auth(admin_user, ADMIN_PASSWORD).get("/api/v1/admin/charts/?days=7").data
    instagram = next(row for row in charts["popular_services"] if row["slug"] == "instagram")
    assert instagram["orders"] == 2
    assert Decimal(instagram["revenue"]) == Decimal(delivered.price)
