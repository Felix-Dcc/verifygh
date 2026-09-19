"""Admin API: least privilege, mandatory reasons, and a complete audit trail."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.constants import Role
from apps.audit.models import AdminAction
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

PASSWORDS = {
    "admin@verifygh.local": "Correct-Horse-Battery-3",
    "support@verifygh.local": "Correct-Horse-Battery-4",
}


@pytest.fixture
def as_admin(api, admin_user, auth):
    return auth(admin_user, PASSWORDS[admin_user.email])


@pytest.fixture
def as_support(api, support_user, auth):
    return auth(support_user, PASSWORDS[support_user.email])


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


ADMIN_ENDPOINTS = [
    "/api/v1/admin/overview/",
    "/api/v1/admin/charts/",
    "/api/v1/admin/health/",
    "/api/v1/admin/users/",
    "/api/v1/admin/orders/",
    "/api/v1/admin/payments/",
    "/api/v1/admin/audit/",
]


@pytest.mark.parametrize("url", ADMIN_ENDPOINTS)
def test_anonymous_cannot_reach_admin(api, url):
    assert api.get(url).status_code == 401


@pytest.mark.parametrize("url", ADMIN_ENDPOINTS)
def test_a_normal_user_cannot_reach_admin(user, auth, url):
    client = auth(user)
    assert client.get(url).status_code == 403


def test_support_can_read_but_not_adjust_a_wallet(as_support, user):
    assert as_support.get("/api/v1/admin/users/").status_code == 200

    response = as_support.post(
        f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
        {"amount": "50.00", "direction": "CREDIT", "reason": "Trying it on"},
        format="json",
    )
    assert response.status_code == 403
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_support_cannot_suspend_a_user(as_support, user):
    response = as_support.post(
        f"/api/v1/admin/users/{user.id}/suspend/",
        {"reason": "Not my call to make"},
        format="json",
    )
    assert response.status_code == 403
    user.refresh_from_db()
    assert user.is_suspended is False


def test_support_cannot_change_pricing(as_support):
    response = as_support.get("/api/v1/admin/pricing-rules/")
    assert response.status_code == 403


def test_a_super_admin_can_do_all_of_it(as_admin, user):
    assert as_admin.get("/api/v1/admin/pricing-rules/").status_code == 200
    assert as_admin.get("/api/v1/admin/users/").status_code == 200


def test_a_suspended_admin_loses_access(as_admin, admin_user):
    admin_user.is_suspended = True
    admin_user.save(update_fields=["is_suspended"])
    assert as_admin.get("/api/v1/admin/overview/").status_code == 403


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------


def test_suspension_requires_a_reason(as_admin, user):
    no_reason = as_admin.post(
        f"/api/v1/admin/users/{user.id}/suspend/", {}, format="json"
    )
    too_short = as_admin.post(
        f"/api/v1/admin/users/{user.id}/suspend/", {"reason": "no"}, format="json"
    )

    assert no_reason.status_code == 400
    assert too_short.status_code == 400
    user.refresh_from_db()
    assert user.is_suspended is False


def test_suspension_works_and_is_audited(as_admin, admin_user, user):
    response = as_admin.post(
        f"/api/v1/admin/users/{user.id}/suspend/",
        {"reason": "Chargeback fraud under investigation"},
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.is_suspended is True
    assert user.suspension_reason == "Chargeback fraud under investigation"

    entry = AdminAction.objects.get(action="USER_SUSPEND")
    assert entry.admin == admin_user
    assert entry.reason == "Chargeback fraud under investigation"
    assert entry.target_id == str(user.id)


def test_an_admin_cannot_suspend_themselves(as_admin, admin_user):
    response = as_admin.post(
        f"/api/v1/admin/users/{admin_user.id}/suspend/",
        {"reason": "Locking myself out by accident"},
        format="json",
    )
    assert response.status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.is_suspended is False


def test_unsuspension_restores_access(as_admin, user):
    as_admin.post(
        f"/api/v1/admin/users/{user.id}/suspend/", {"reason": "Investigating"}, format="json"
    )
    response = as_admin.post(
        f"/api/v1/admin/users/{user.id}/unsuspend/",
        {"reason": "Investigation closed, no issue found"},
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.is_suspended is False
    assert AdminAction.objects.filter(action="USER_UNSUSPEND").exists()


# ---------------------------------------------------------------------------
# Wallet adjustment
# ---------------------------------------------------------------------------


def test_wallet_adjustment_writes_a_ledger_entry_and_an_admin_action(as_admin, user):
    response = as_admin.post(
        f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
        {"amount": "25.00", "direction": "CREDIT",
         "reason": "Goodwill for the outage on 14 September"},
        format="json",
    )

    assert response.status_code == 200
    wallet = get_or_create_wallet(user)
    assert wallet.balance == Decimal("25.00")

    entry = WalletLedgerEntry.objects.get(
        wallet=wallet, entry_type=LedgerEntryType.ADJUSTMENT
    )
    assert entry.created_by_id is not None
    assert "Goodwill" in entry.description
    assert AdminAction.objects.filter(action="WALLET_ADJUST").exists()
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_wallet_adjustment_requires_a_reason(as_admin, user):
    response = as_admin.post(
        f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
        {"amount": "25.00", "direction": "CREDIT"},
        format="json",
    )
    assert response.status_code == 400
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_debit_adjustment_cannot_push_a_wallet_negative(as_admin, user, funded_wallet):
    funded_wallet(user, "10.00")

    response = as_admin.post(
        f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
        {"amount": "50.00", "direction": "DEBIT", "reason": "Recovering a duplicate credit"},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert get_or_create_wallet(user).balance == Decimal("10.00")


# ---------------------------------------------------------------------------
# Metrics and catalog
# ---------------------------------------------------------------------------


def test_overview_reports_the_business_numbers(as_admin, user, catalog):
    response = as_admin.get("/api/v1/admin/overview/")

    assert response.status_code == 200
    for section in ("users", "revenue", "orders", "payments", "refunds", "flags"):
        assert section in response.data
    assert response.data["revenue"]["currency"] == "GHS"


def test_charts_return_series_the_dashboard_can_draw(as_admin, catalog):
    response = as_admin.get("/api/v1/admin/charts/?days=7")

    assert response.status_code == 200
    assert response.data["days"] == 7
    for key in ("revenue", "orders", "popular_services", "payment_methods", "failure_rate"):
        assert key in response.data


def test_health_reports_that_we_are_running_on_mocks(as_admin, catalog):
    response = as_admin.get("/api/v1/admin/health/")

    assert response.status_code == 200
    assert response.data["verification_provider"]["is_mock"] is True
    assert response.data["payment_provider"]["is_mock"] is True
    assert response.data["exchange_rate"]["configured"] is True


def test_offerings_show_provider_cost_beside_customer_price(as_admin, catalog):
    response = as_admin.get("/api/v1/admin/offerings/?service=instagram")

    assert response.status_code == 200
    row = response.data["results"][0]
    assert Decimal(row["cost_amount"]) > 0
    assert Decimal(row["customer_price"]) > Decimal(row["cost_amount"])
    assert row["pricing_error"] == ""


def test_disabling_a_service_removes_it_from_the_marketplace(as_admin, api, catalog):
    before = api.get("/api/v1/services/?search=instagram").data
    assert before["count"] == 1

    response = as_admin.patch(
        "/api/v1/admin/services/instagram/",
        {"is_enabled": False, "reason": "Provider quality issues"},
        format="json",
    )
    assert response.status_code == 200

    after = api.get("/api/v1/services/?search=instagram").data
    assert after["count"] == 0
    assert AdminAction.objects.filter(action="SERVICE_UPDATE").exists()


def test_maintenance_mode_keeps_the_service_visible_but_unavailable(as_admin, api, catalog):
    as_admin.patch(
        "/api/v1/admin/services/instagram/",
        {"is_maintenance": True, "maintenance_note": "Back shortly",
         "reason": "Upstream maintenance"},
        format="json",
    )

    service = api.get("/api/v1/services/instagram/").data
    assert service["is_maintenance"] is True
    assert service["available"] is False
    assert service["maintenance_note"] == "Back shortly"


def test_setting_a_new_exchange_rate_appends_and_reprices(as_admin, api, catalog):
    before = Decimal(api.get("/api/v1/services/instagram/").data["from_price"])

    response = as_admin.post(
        "/api/v1/admin/exchange-rates/",
        {"rate": "24.000000", "reason": "Cedi moved"},
        format="json",
    )
    assert response.status_code == 201

    after = Decimal(api.get("/api/v1/services/instagram/").data["from_price"])
    assert after > before
    assert AdminAction.objects.filter(action="EXCHANGE_RATE_SET").exists()


def test_the_global_default_pricing_rule_cannot_be_deleted(as_admin, pricing_rule):
    response = as_admin.delete(f"/api/v1/admin/pricing-rules/{pricing_rule.id}/")
    assert response.status_code == 409


def test_admin_order_list_never_exposes_verification_codes(as_admin, user, catalog):
    """Support can see that a code arrived, never what it was."""
    from apps.catalog.models import Country, Provider, Service
    from apps.orders.models import Order

    Order.objects.create(
        reference="VGH-TESTAA",
        user=user,
        service=Service.objects.get(slug="instagram"),
        country=Country.objects.get(code="US"),
        provider=Provider.objects.first(),
        price=Decimal("15.00"),
        idempotency_key="admin-code-test",
        verification_code="123456",
    )

    response = as_admin.get("/api/v1/admin/orders/")
    row = next(item for item in response.data["results"] if item["reference"] == "VGH-TESTAA")

    assert row["has_code"] is True
    assert "verification_code" not in row


def test_admin_role_change_is_restricted_to_super_admin(as_admin, user):
    """A support user promoting themselves would defeat the whole matrix."""
    from apps.accounts.constants import ROLE_PERMISSIONS, AdminPermission

    assert AdminPermission.USER_ROLE_CHANGE in ROLE_PERMISSIONS[Role.SUPER_ADMIN]
    assert AdminPermission.USER_ROLE_CHANGE not in ROLE_PERMISSIONS[Role.ADMIN]
    assert AdminPermission.USER_ROLE_CHANGE not in ROLE_PERMISSIONS[Role.SUPPORT]
    assert ROLE_PERMISSIONS[Role.USER] == set()


def test_support_can_see_abuse_signals_but_not_dismiss_them(as_support, user):
    from apps.audit.models import SuspiciousActivity

    flag = SuspiciousActivity.objects.create(user=user, kind="SHARED_DEVICE", level="LOW")

    assert as_support.get("/api/v1/admin/flags/").status_code == 200
    response = as_support.post(f"/api/v1/admin/flags/{flag.id}/resolve/",
                               {"note": "Looks fine"}, format="json")
    assert response.status_code == 403
    flag.refresh_from_db()
    assert flag.resolved is False
