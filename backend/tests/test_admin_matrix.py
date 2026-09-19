"""Every admin mutation, against every role.

Two properties per endpoint:
  * a role without the permission gets 403 and changes nothing - not even an
    audit row;
  * a role with it succeeds and leaves exactly one AdminAction, committed with
    the effect (never before it, never without it).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.constants import ROLE_PERMISSIONS, AdminPermission, Role
from apps.accounts.models import User
from apps.audit.models import AdminAction, SuspiciousActivity
from apps.catalog.models import ProviderService
from apps.orders.models import Order, OrderStatus
from apps.pricing.models import MarkupType, PricingRule
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-9"


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
def world(user, catalog, funded_wallet):
    """One customer with money, one failed order, one flag, one offering."""
    from apps.orders.services import create_order

    funded_wallet(user, "100.00")
    order = create_order(user=user, service_slug="instagram", country_code="US",
                         idempotency_key="matrix")
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.FAILED)
    flag = SuspiciousActivity.objects.create(user=user, kind="SHARED_DEVICE", level="LOW")
    offering = ProviderService.objects.select_related("service", "country").first()
    return {"user": user, "order": Order.objects.get(pk=order.pk), "flag": flag,
            "offering": offering}


def endpoints(w):
    user, order = w["user"], w["order"]
    reason = {"reason": "Matrix test reason"}
    return [
        ("post", f"/api/v1/admin/users/{user.id}/suspend/", reason,
         AdminPermission.USER_SUSPEND),
        ("post", f"/api/v1/admin/users/{user.id}/unsuspend/", reason,
         AdminPermission.USER_SUSPEND),
        ("post", f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
         {"amount": "5.00", "direction": "CREDIT", **reason}, AdminPermission.WALLET_ADJUST),
        ("post", f"/api/v1/admin/orders/{order.reference}/refund/", reason,
         AdminPermission.ORDER_REFUND),
        ("patch", f"/api/v1/admin/services/{w['offering'].service.slug}/",
         {"is_enabled": False, **reason}, AdminPermission.CATALOG_MANAGE),
        ("patch", f"/api/v1/admin/countries/{w['offering'].country.code}/",
         {"is_enabled": False, **reason}, AdminPermission.CATALOG_MANAGE),
        ("patch", f"/api/v1/admin/offerings/{w['offering'].id}/",
         {"is_enabled": False, **reason}, AdminPermission.CATALOG_MANAGE),
        ("post", "/api/v1/admin/pricing-rules/",
         {"name": "Matrix rule", "markup_type": MarkupType.PERCENTAGE, "markup_value": "10.00",
          "priority": 10, **reason}, AdminPermission.PRICING_MANAGE),
        ("post", "/api/v1/admin/exchange-rates/", {"rate": "15.5000", **reason},
         AdminPermission.PRICING_MANAGE),
        ("post", f"/api/v1/admin/flags/{w['flag'].id}/resolve/", {"note": "Checked"},
         AdminPermission.USER_SUSPEND),
    ]


@pytest.mark.parametrize("role", [Role.USER, Role.SUPPORT, Role.ADMIN, Role.SUPER_ADMIN])
def test_every_admin_mutation_obeys_the_role_matrix(role, staff, signed_in, world):
    actor = staff(role)
    client = signed_in(actor)
    granted = ROLE_PERMISSIONS[role]

    for method, url, body, permission in endpoints(world):
        actions_before = AdminAction.objects.count()
        ledger_before = WalletLedgerEntry.objects.count()
        response = getattr(client, method)(url, body, format="json")

        if str(permission) not in granted:
            assert response.status_code == 403, (role, url, response.status_code)
            assert AdminAction.objects.count() == actions_before, (role, url)
            assert WalletLedgerEntry.objects.count() == ledger_before, (role, url)
        else:
            assert response.status_code in (200, 201), (role, url, response.data)
            assert AdminAction.objects.count() == actions_before + 1, (role, url)
            assert AdminAction.objects.latest("created_at").admin_id == actor.pk


def test_a_refused_debit_leaves_no_admin_action(staff, signed_in, user):
    client = signed_in(staff(Role.SUPER_ADMIN))
    response = client.post(f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
                           {"amount": "50.00", "direction": "DEBIT",
                            "reason": "Would overdraw"}, format="json")

    assert response.status_code == 409
    assert not AdminAction.objects.filter(action="WALLET_ADJUST").exists()


def test_an_adjustment_record_carries_the_real_before_and_after(staff, signed_in, user,
                                                                funded_wallet):
    funded_wallet(user, "20.00")
    client = signed_in(staff(Role.SUPER_ADMIN))
    client.post(f"/api/v1/admin/users/{user.id}/wallet-adjustment/",
                {"amount": "5.00", "direction": "DEBIT", "reason": "Chargeback fee"},
                format="json")

    record = AdminAction.objects.get(action="WALLET_ADJUST")
    entry = WalletLedgerEntry.objects.get(entry_type=LedgerEntryType.ADJUSTMENT)
    assert record.before["balance"] == "20.00"
    assert record.after["balance"] == "15.00"
    assert record.after["ledger_reference"] == entry.reference


def test_a_resubmitted_adjustment_moves_money_once(staff, signed_in, user):
    client = signed_in(staff(Role.SUPER_ADMIN))
    body = {"amount": "10.00", "direction": "CREDIT", "reason": "Goodwill credit"}
    for _ in range(3):
        response = client.post(f"/api/v1/admin/users/{user.id}/wallet-adjustment/", body,
                               format="json", HTTP_X_IDEMPOTENCY_KEY="form-submit-1")
        assert response.status_code == 200

    assert get_or_create_wallet(user).balance == Decimal("10.00")
    assert AdminAction.objects.filter(action="WALLET_ADJUST").count() == 1


def test_an_admin_refund_that_is_declined_says_so(staff, signed_in, world):
    """Completed orders are not refundable; the console used to report success."""
    order = world["order"]
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.COMPLETED)
    client = signed_in(staff(Role.ADMIN))
    response = client.post(f"/api/v1/admin/orders/{order.reference}/refund/",
                           {"reason": "Customer asked"}, format="json")

    assert response.status_code == 409
    assert not AdminAction.objects.filter(action="ORDER_REFUND").exists()


def test_a_failed_audit_write_undoes_the_suspension(staff, signed_in, user, monkeypatch):
    """The audit record is not best-effort for privileged actions."""
    from apps.adminapi import views

    def broken(**kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(views, "record_admin_action", broken)
    client = signed_in(staff(Role.SUPER_ADMIN))
    client.raise_request_exception = False
    response = client.post(f"/api/v1/admin/users/{user.id}/suspend/",
                           {"reason": "Fraud report"}, format="json")

    assert response.status_code == 500
    user.refresh_from_db()
    assert user.is_suspended is False
    assert user.token_version == 0


def test_offering_edits_are_limited_to_enabling(staff, signed_in, world):
    offering = world["offering"]
    client = signed_in(staff(Role.SUPER_ADMIN))
    client.patch(f"/api/v1/admin/offerings/{offering.id}/",
                 {"provider_service_code": "something-else", "ttl_minutes": 999,
                  "is_available": True, "reason": "Trying"}, format="json")

    fresh = ProviderService.objects.get(pk=offering.pk)
    assert fresh.provider_service_code == offering.provider_service_code
    assert fresh.ttl_minutes == offering.ttl_minutes


def test_catalog_edits_record_every_changed_field(staff, signed_in, world):
    service = world["offering"].service
    client = signed_in(staff(Role.ADMIN))
    client.patch(f"/api/v1/admin/services/{service.slug}/",
                 {"name": "Renamed", "is_enabled": True, "reason": "Rebrand"}, format="json")

    record = AdminAction.objects.get(action="SERVICE_UPDATE")
    assert record.before == {"name": service.name}
    assert record.after == {"name": "Renamed"}
    assert record.reason == "Rebrand"


def test_the_role_matrix_is_what_the_docs_say(settings_obj=settings):
    """Money-moving powers stay with super admins only."""
    assert AdminPermission.WALLET_ADJUST not in ROLE_PERMISSIONS[Role.ADMIN]
    assert AdminPermission.PRICING_MANAGE not in ROLE_PERMISSIONS[Role.ADMIN]
    assert AdminPermission.PROVIDER_MANAGE not in ROLE_PERMISSIONS[Role.ADMIN]
    assert not {AdminPermission.USER_SUSPEND, AdminPermission.ORDER_REFUND,
                AdminPermission.CATALOG_MANAGE} & ROLE_PERMISSIONS[Role.SUPPORT]
    assert PricingRule  # imported for the matrix endpoints
