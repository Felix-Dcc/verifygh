"""The "Pause site" button.

Production, 6 Oct 2026: the number provider stopped handing out numbers, and
every order was charged, failed and refunded twenty seconds later. Staff need
one switch that stops customers up front - while everything already in flight
carries on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AdminAction
from apps.common import maintenance
from apps.common.errors import ServiceUnavailable
from apps.common.models import MaintenanceMode, MaintenanceState
from apps.orders.models import Order
from apps.payments.services import deposits_blocked_reason, initiate_deposit
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

STATUS = "/api/v1/status/"
ADMIN = "/api/v1/admin/maintenance/"
ADMIN_PASSWORD = "Correct-Horse-Battery-3"


#: The switch publishes its new state once the change commits, which never
#: happens inside pytest-django's wrapping transaction unless asked.
_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _on_commit
    _on_commit = django_capture_on_commit_callbacks
    yield
    _on_commit = None


def pause(client, mode="BUYING_PAUSED", reason="Numbers unavailable from our supplier", **extra):
    with _on_commit(execute=True):
        return client.post(ADMIN, {"mode": mode, "reason": reason, **extra}, format="json")


def set_state(mode):
    MaintenanceState.objects.update_or_create(pk=1, defaults={"mode": mode})
    maintenance.cache.delete(maintenance.CACHE_KEY)


def buy(client):
    return client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                       format="json")


# -- the switch ---------------------------------------------------------------


def test_the_site_starts_open(api):
    data = api.get(STATUS).data
    assert data["mode"] == "OFF"
    assert data["buying_open"] is True and data["deposits_open"] is True
    assert data["message"] == ""


def test_pausing_shows_everyone_the_notice_at_once(admin_user, auth):
    staff = auth(admin_user, ADMIN_PASSWORD)
    assert api_status() == "OFF"  # cached as open...
    response = pause(staff, expected_back_minutes=60)
    assert response.status_code == 200, response.data

    seen = APIClient().get(STATUS).data  # ...and replaced at once, signed out too
    assert seen["mode"] == "BUYING_PAUSED"
    assert seen["buying_open"] is False and seen["deposits_open"] is True
    assert seen["message"] == maintenance.BUYING_NOTICE
    assert seen["since"] and seen["expected_back_at"]

    action = AdminAction.objects.get(action="MAINTENANCE_ON")
    assert action.admin == admin_user
    assert action.reason == "Numbers unavailable from our supplier"


def api_status():
    return APIClient().get(STATUS).data["mode"]


def test_staff_are_told(admin_user, auth):
    from apps.notifications.models import Notification

    pause(auth(admin_user, ADMIN_PASSWORD))
    note = Notification.objects.get(user=admin_user, event="STAFF_MAINTENANCE",
                                    channel="IN_APP")
    assert note.title == "Site paused: buying"
    assert note.metadata["admin_link"] == "/admin/system"


def test_reopening_is_audited_and_clears_the_notice(admin_user, auth):
    staff = auth(admin_user, ADMIN_PASSWORD)
    pause(staff, mode="ALL_PAUSED")
    response = pause(staff, mode="OFF", reason="Supplier is back")
    assert response.status_code == 200
    assert api_status() == "OFF"
    assert APIClient().get(STATUS).data["since"] is None
    assert AdminAction.objects.filter(action="MAINTENANCE_OFF",
                                      reason="Supplier is back").exists()


def test_changing_level_keeps_when_it_started(admin_user, auth):
    staff = auth(admin_user, ADMIN_PASSWORD)
    pause(staff)
    since = APIClient().get(STATUS).data["since"]
    pause(staff, mode="ALL_PAUSED")
    data = APIClient().get(STATUS).data
    assert data["mode"] == "ALL_PAUSED" and data["since"] == since
    assert data["message"] == maintenance.ALL_NOTICE
    assert AdminAction.objects.filter(action="MAINTENANCE_CHANGED").exists()


def test_a_custom_notice_replaces_the_default(admin_user, auth):
    pause(auth(admin_user, ADMIN_PASSWORD), message="Back at 10pm.")
    assert APIClient().get(STATUS).data["message"] == "Back at 10pm."


@pytest.mark.parametrize("body", [
    {"mode": "SOMETIMES", "reason": "Planned update"},
    {"mode": "BUYING_PAUSED", "reason": ""},
    {"mode": "BUYING_PAUSED", "reason": "Planned update", "expected_back_minutes": 0},
    {"mode": "BUYING_PAUSED", "reason": "Planned update", "expected_back_minutes": "soon"},
    {"mode": "BUYING_PAUSED", "reason": "Planned update", "message": "x" * 301},
])
def test_bad_requests_change_nothing(admin_user, auth, body):
    response = auth(admin_user, ADMIN_PASSWORD).post(ADMIN, body, format="json")
    assert response.status_code == 400
    assert MaintenanceState.objects.get(pk=1).mode == MaintenanceMode.OFF


def test_support_staff_can_see_it_but_not_press_it(support_user, auth):
    client = auth(support_user, "Correct-Horse-Battery-4")
    assert client.get(ADMIN).status_code == 200
    assert pause(client).status_code == 403
    assert api_status() == "OFF"


def test_customers_cannot_press_it(user, auth):
    client = auth(user)
    assert client.get(ADMIN).status_code == 403
    assert pause(client).status_code == 403


def test_the_admin_report_carries_the_presets(admin_user, auth):
    data = auth(admin_user, ADMIN_PASSWORD).get(ADMIN).data
    assert data["preset_reasons"] == list(maintenance.PRESET_REASONS)
    assert set(data["notices"]) == {"BUYING_PAUSED", "DEPOSITS_PAUSED", "ALL_PAUSED"}


# -- what it stops ------------------------------------------------------------


def test_orders_are_refused_before_any_money_moves(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    wallet = funded_wallet(user, "200.00")
    set_state(MaintenanceMode.BUYING_PAUSED)
    client = auth(user)

    eligibility = client.get("/api/v1/orders/eligibility/").data
    assert eligibility == {"eligible": False, "code": "MAINTENANCE",
                           "message": maintenance.BUYING_NOTICE}
    response = buy(client)
    assert response.status_code == 503
    assert response.data["error"]["code"] == "MAINTENANCE"
    assert Order.objects.count() == 0
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_pausing_buying_leaves_top_ups_open(user, catalog):
    set_state(MaintenanceMode.BUYING_PAUSED)
    assert deposits_blocked_reason() == ""


def test_pausing_everything_closes_top_ups_whatever_the_catalogue_says(user, catalog,
                                                                        settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    set_state(MaintenanceMode.ALL_PAUSED)
    assert deposits_blocked_reason() == maintenance.ALL_NOTICE
    with pytest.raises(ServiceUnavailable) as raised:
        initiate_deposit(user=user, amount=Decimal("20.00"), phone="+233241234567",
                         network="MTN")
    assert raised.value.code == "DEPOSITS_PAUSED"


def test_pausing_top_ups_keeps_buying_open(user, auth, catalog, funded_wallet, settings):
    """8 Oct 2026: the payment provider disabled the business; the number
    provider was fine, and customers had balances to spend."""
    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    set_state(MaintenanceMode.DEPOSITS_PAUSED)

    status = maintenance.current()
    assert status["buying_open"] is True and status["deposits_open"] is False
    assert status["message"] == maintenance.DEPOSITS_NOTICE
    assert deposits_blocked_reason() == maintenance.DEPOSITS_NOTICE
    with pytest.raises(ServiceUnavailable):
        initiate_deposit(user=user, amount=Decimal("20.00"), phone="+233241234567",
                         network="MTN")

    client = auth(user)
    assert client.get("/api/v1/orders/eligibility/").data["eligible"] is True
    with _on_commit(execute=True):
        assert buy(client).status_code == 201


def test_the_deposit_screen_is_told(api, catalog):
    set_state(MaintenanceMode.ALL_PAUSED)
    data = api.get("/api/v1/payments/options/").data
    assert data["deposits_enabled"] is False
    assert data["deposits_disabled_reason"] == maintenance.ALL_NOTICE


def test_a_retried_purchase_still_returns_its_order(user, auth, catalog, funded_wallet):
    """An order placed before the pause, retried with the same key, is the
    customer's own order - not a new purchase to refuse."""
    verification_mock.force_scenario("SLOW_CODE")
    funded_wallet(user, "200.00")
    client = auth(user)
    first = client.post("/api/v1/orders/", {"service": "instagram", "country": "US",
                                            "idempotency_key": "same"}, format="json")
    assert first.status_code == 201
    set_state(MaintenanceMode.BUYING_PAUSED)
    again = client.post("/api/v1/orders/", {"service": "instagram", "country": "US",
                                            "idempotency_key": "same"}, format="json")
    assert again.data["reference"] == first.data["reference"]


# -- what it never stops ------------------------------------------------------


def test_orders_already_waiting_are_still_polled(user, auth, catalog, funded_wallet):
    from apps.orders.services import poll_order

    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    with _on_commit(execute=True):
        reference = buy(auth(user)).data["reference"]
    set_state(MaintenanceMode.ALL_PAUSED)

    order = Order.objects.get(reference=reference)
    verification_mock.fast_forward(order.provider_order_id, 60)
    order = poll_order(Order.objects.get(pk=order.pk))
    assert order.code_received_at is not None


def test_an_otp_deposit_already_started_still_completes(user, monkeypatch):
    """A Telecel customer typing the code from their SMS while staff pause."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.payments import services as payment_services
    from apps.payments.base import ChargeDTO, ChargeStatus
    from apps.payments.models import Payment, PaymentStatus
    from apps.payments.services import submit_deposit_otp

    payment = Payment.objects.create(
        user=user, reference="VGH-PAY-MAINT001", provider="paystack",
        provider_reference="VGH-PAY-MAINT001", amount=Decimal("10.00"), currency="GHS",
        phone="+233201234567", network="TELECEL", status=PaymentStatus.OTP_REQUIRED,
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    class Provider:
        key = "paystack"

        def submit_otp(self, *, reference, otp):
            return ChargeDTO(provider_reference=reference,
                             status=ChargeStatus.PHONE_AUTH_REQUIRED,
                             instructions="Approve on your phone")

    monkeypatch.setattr(payment_services, "get_payment_provider", lambda *a, **k: Provider())
    set_state(MaintenanceMode.ALL_PAUSED)

    payment = submit_deposit_otp(user=user, reference=payment.reference, otp="123456")
    assert payment.status == PaymentStatus.PHONE_AUTH


def test_admin_still_works_while_paused(admin_user, auth):
    set_state(MaintenanceMode.ALL_PAUSED)
    staff = auth(admin_user, ADMIN_PASSWORD)
    assert staff.get("/api/v1/admin/overview/").status_code == 200
    assert pause(staff, mode="OFF", reason="Back").status_code == 200


def test_signing_in_still_works_while_paused(user, api):
    set_state(MaintenanceMode.ALL_PAUSED)
    response = api.post("/api/v1/auth/login/", {"email": user.email,
                                                "password": "Correct-Horse-Battery-1"},
                        format="json")
    assert response.status_code == 200


# -- resilience ---------------------------------------------------------------


def test_an_unreadable_cache_falls_back_to_the_database(monkeypatch):
    set_state(MaintenanceMode.BUYING_PAUSED)

    def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(maintenance.cache, "get", broken)
    monkeypatch.setattr(maintenance.cache, "set", broken)
    assert maintenance.current()["buying_open"] is False


def test_a_refusal_is_not_logged_as_a_server_error(user, auth, catalog, caplog):
    set_state(MaintenanceMode.BUYING_PAUSED)
    with caplog.at_level("ERROR"):
        assert buy(auth(user)).status_code == 503
    assert not [r for r in caplog.records if r.getMessage() == "api_error"]
