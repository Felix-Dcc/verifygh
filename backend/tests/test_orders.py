"""The purchase flow, end to end, against the mock provider."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.orders.models import Order, OrderStatus, Refund, RefundStatus
from apps.orders.services import poll_order
from apps.verification import mock as verification_mock
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db


#: The order endpoint dispatches provider fulfilment via transaction.on_commit,
#: which never fires inside pytest-django's wrapping transaction. Capture and
#: run those callbacks so the tests exercise the real post-commit path.
_capture_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture_on_commit
    _capture_on_commit = django_capture_on_commit_callbacks
    yield
    _capture_on_commit = None


def buy(client, service="instagram", country="US", key=None):
    body = {"service": service, "country": country}
    if key:
        body["idempotency_key"] = key
    with _capture_on_commit(execute=True):
        response = client.post("/api/v1/orders/", body, format="json")
    return response


def drive(order: Order, seconds: int = 30) -> Order:
    """Fast-forward the mock provider and poll, without sleeping."""
    verification_mock.fast_forward(order.provider_order_id, seconds)
    return poll_order(Order.objects.get(pk=order.pk))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_purchase_to_completion(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    response = buy(client)
    assert response.status_code == 201, response.data

    reference = response.data["reference"]
    order = Order.objects.get(reference=reference)

    # Money left the wallet, and the number was assigned by the mock provider.
    price = Decimal(response.data["price"])
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - price
    assert order.status == OrderStatus.WAITING_FOR_CODE
    assert order.phone_number.startswith("+1")

    order = drive(order, seconds=30)
    assert order.status == OrderStatus.CODE_RECEIVED
    assert len(order.verification_code) == 6

    detail = client.get(f"/api/v1/orders/{reference}/").data
    assert detail["verification_code"] == order.verification_code
    assert detail["code_display_allowed"] is True

    complete = client.post(f"/api/v1/orders/{reference}/complete/", {}, format="json")
    assert complete.status_code == 200
    assert complete.data["status"] == OrderStatus.COMPLETED

    # A delivered service is not refunded.
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - price
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_order_timeline_reads_like_the_ui_shows_it(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]
    order = drive(Order.objects.get(reference=reference), seconds=30)

    labels = [event.label for event in order.events.all()]
    assert labels[:4] == [
        "Order created",
        "Payment confirmed",
        "Number assigned",
        "Waiting for verification code",
    ]
    assert "Verification code received" in labels


# ---------------------------------------------------------------------------
# Money rules
# ---------------------------------------------------------------------------


def test_insufficient_balance_blocks_the_purchase_and_writes_nothing(
    user, auth, catalog, funded_wallet
):
    funded_wallet(user, "1.00")
    client = auth(user)

    response = buy(client)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert "shortfall" in response.data["error"]["details"]
    assert Order.objects.count() == 0
    assert get_or_create_wallet(user).balance == Decimal("1.00")


def test_client_cannot_dictate_the_price(user, auth, catalog, funded_wallet):
    """A price in the request body is ignored entirely."""
    verification_mock.force_scenario("HAPPY")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    response = client.post(
        "/api/v1/orders/",
        {"service": "instagram", "country": "US", "price": "0.01", "amount": "0.01"},
        format="json",
    )
    assert response.status_code == 201

    order = Order.objects.get(reference=response.data["reference"])
    assert order.price > Decimal("1.00")

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - order.price


def test_repeating_an_idempotency_key_does_not_buy_twice(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    first = buy(client, key="stable-key-1")
    second = buy(client, key="stable-key-1")

    assert first.status_code == 201
    assert second.data["reference"] == first.data["reference"]
    assert Order.objects.count() == 1

    wallet.refresh_from_db()
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.PURCHASE
    ).count() == 1


def test_price_snapshot_is_frozen_onto_the_order(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)

    order = Order.objects.get(reference=buy(client).data["reference"])

    assert order.exchange_rate == Decimal("12.000000")
    assert order.provider_cost > 0
    assert order.price_breakdown["pricing_rule_name"] == "Test global default"
    assert Decimal(order.price_breakdown["customer_price"]) == order.price


# ---------------------------------------------------------------------------
# Failure paths and refunds
# ---------------------------------------------------------------------------


def test_provider_with_no_stock_fails_and_refunds_automatically(
    user, auth, catalog, funded_wallet
):
    verification_mock.force_scenario("NO_STOCK")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    response = buy(client)
    order = Order.objects.get(reference=response.data["reference"])

    assert order.status == OrderStatus.REFUNDED
    assert order.refund_status == RefundStatus.COMPLETED

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_provider_error_fails_and_refunds_automatically(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("PROVIDER_ERR")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    order = Order.objects.get(reference=buy(client).data["reference"])

    assert order.status == OrderStatus.REFUNDED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_expiry_without_a_code_refunds_the_user(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("NO_CODE")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    order = Order.objects.get(reference=buy(client).data["reference"])
    assert order.status == OrderStatus.WAITING_FOR_CODE

    # Push past the number's TTL and run the sweeper.
    Order.objects.filter(pk=order.pk).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )
    from apps.orders.tasks import expire_stale_orders

    expire_stale_orders()

    order.refresh_from_db()
    assert order.status == OrderStatus.REFUNDED
    assert order.refund_status == RefundStatus.COMPLETED

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_a_refund_is_never_issued_twice(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("NO_STOCK")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    order = Order.objects.get(reference=buy(client).data["reference"])

    from apps.orders.models import RefundReason
    from apps.orders.services import issue_refund

    for _ in range(3):
        issue_refund(order, reason=RefundReason.PROVIDER_FAILED)

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert Refund.objects.filter(order=order).count() == 1
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.REFUND
    ).count() == 1


def test_cancelling_before_a_code_refunds(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("SLOW_CODE")
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]
    response = client.post(f"/api/v1/orders/{reference}/cancel/", {}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == OrderStatus.REFUNDED

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_cancelling_after_the_code_arrives_is_refused(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]
    drive(Order.objects.get(reference=reference), seconds=30)

    response = client.post(f"/api/v1/orders/{reference}/cancel/", {}, format="json")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "CANCEL_NOT_ALLOWED"


def test_completing_before_a_code_arrives_is_refused(user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("SLOW_CODE")
    funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]
    response = client.post(f"/api/v1/orders/{reference}/complete/", {}, format="json")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# Eligibility and limits
# ---------------------------------------------------------------------------


def test_unverified_email_blocks_purchase(user, auth, catalog, funded_wallet):
    user.is_email_verified = False
    user.save(update_fields=["is_email_verified"])
    funded_wallet(user, "200.00")
    client = auth(user)

    response = buy(client)
    assert response.status_code == 403
    assert response.data["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_not_accepting_the_current_terms_blocks_purchase(user, auth, catalog, funded_wallet):
    user.accepted_terms_version = ""
    user.save(update_fields=["accepted_terms_version"])
    funded_wallet(user, "200.00")
    client = auth(user)

    response = buy(client)
    assert response.status_code == 403
    assert response.data["error"]["code"] == "TERMS_NOT_ACCEPTED"


def test_suspended_account_cannot_buy(user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)

    user.is_suspended = True
    user.save(update_fields=["is_suspended"])

    response = buy(client)
    assert response.status_code == 403


def test_active_order_cap_is_enforced(user, auth, catalog, funded_wallet, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_ACTIVE_ORDERS": 2}
    verification_mock.force_scenario("SLOW_CODE")
    funded_wallet(user, "500.00")
    client = auth(user)

    assert buy(client, key="a").status_code == 201
    assert buy(client, key="b").status_code == 201

    response = buy(client, key="c")
    assert response.status_code == 429
    assert response.data["error"]["code"] == "TOO_MANY_ACTIVE_ORDERS"


def test_eligibility_endpoint_explains_the_blocker(user, auth, catalog):
    user.is_email_verified = False
    user.save(update_fields=["is_email_verified"])
    client = auth(user)

    response = client.get("/api/v1/orders/eligibility/")
    assert response.data["eligible"] is False
    assert response.data["code"] == "EMAIL_NOT_VERIFIED"


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_a_user_cannot_read_another_users_order(user, other_user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    owner_client = auth(user)
    reference = buy(owner_client).data["reference"]

    from rest_framework.test import APIClient

    intruder = APIClient()
    login = intruder.post(
        "/api/v1/auth/login/",
        {"email": other_user.email, "password": "Correct-Horse-Battery-2"},
        format="json",
    )
    intruder.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])

    assert intruder.get(f"/api/v1/orders/{reference}/").status_code == 404
    cancel = intruder.post(f"/api/v1/orders/{reference}/cancel/", {}, format="json")
    assert cancel.status_code == 404


def test_order_list_only_contains_your_own_orders(user, other_user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    funded_wallet(other_user, "200.00")

    owner_client = auth(user)
    buy(owner_client)

    response = owner_client.get("/api/v1/orders/")
    assert response.data["pagination"]["count"] == 1
    assert all(
        Order.objects.get(reference=row["reference"]).user_id == user.id
        for row in response.data["results"]
    )


# ---------------------------------------------------------------------------
# The live status endpoint
# ---------------------------------------------------------------------------


def test_status_endpoint_advances_a_waiting_order(user, auth, catalog, funded_wallet):
    """The user's own polling nudges the provider, within a cooldown.

    Without this, an order only moves when the Celery sweep runs - which means
    a user watching the screen sees nothing for seconds at a time, and a
    developer with no worker running sees nothing at all.
    """
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]
    order = Order.objects.get(reference=reference)
    assert order.status == OrderStatus.WAITING_FOR_CODE

    verification_mock.fast_forward(order.provider_order_id, 30)

    response = client.get(f"/api/v1/orders/{reference}/status/")

    assert response.status_code == 200
    assert response.data["status"] == OrderStatus.CODE_RECEIVED
    assert len(response.data["verification_code"]) == 6
    assert response.data["code_display_allowed"] is True
    assert response.data["poll_interval_seconds"] > 0


def test_status_endpoint_respects_the_poll_cooldown(user, auth, catalog, funded_wallet, settings):
    """A user holding the screen open must not become a stream of upstream calls."""
    from apps.verification import registry

    settings.VERIFYGH = {**settings.VERIFYGH, "ORDER_POLL_SECONDS": 300}
    verification_mock.force_scenario("SLOW_CODE")
    funded_wallet(user, "200.00")
    client = auth(user)

    reference = buy(client).data["reference"]

    calls = {"count": 0}
    original = registry.RateLimitedProvider.get_order_status

    def counting(self, provider_order_id):
        calls["count"] += 1
        return original(self, provider_order_id)

    registry.RateLimitedProvider.get_order_status = counting
    try:
        for _ in range(5):
            client.get(f"/api/v1/orders/{reference}/status/")
    finally:
        registry.RateLimitedProvider.get_order_status = original

    # Five browser polls, one upstream call.
    assert calls["count"] == 1


def test_status_endpoint_is_owner_only(user, other_user, auth, catalog, funded_wallet):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    reference = buy(auth(user)).data["reference"]

    from rest_framework.test import APIClient

    intruder = APIClient()
    login = intruder.post(
        "/api/v1/auth/login/",
        {"email": other_user.email, "password": "Correct-Horse-Battery-2"},
        format="json",
    )
    intruder.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])

    assert intruder.get(f"/api/v1/orders/{reference}/status/").status_code == 404


# ---------------------------------------------------------------------------
# Lifecycle gaps found in the pre-production audit
# ---------------------------------------------------------------------------


def test_delivered_orders_are_auto_completed_and_stop_counting_as_active(
    user, auth, catalog, funded_wallet, settings
):
    """Five codes, never tapped 'complete', must not lock a customer out."""
    from apps.orders.tasks import expire_stale_orders

    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_ACTIVE_ORDERS": 2}
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "500.00")
    client = auth(user)

    for key in ("a", "b"):
        order = Order.objects.get(reference=buy(client, key=key).data["reference"])
        drive(order, seconds=30)

    assert buy(client, key="c").data["error"]["code"] == "TOO_MANY_ACTIVE_ORDERS"

    Order.objects.filter(status=OrderStatus.CODE_RECEIVED).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )
    balance_before = get_or_create_wallet(user).balance
    result = expire_stale_orders()

    assert result["auto_completed"] == 2
    assert Order.objects.filter(status=OrderStatus.COMPLETED).count() == 2
    # Completed, not refunded - the codes were delivered.
    assert get_or_create_wallet(user).balance == balance_before
    assert buy(client, key="c").status_code == 201
    assert verify_wallet_integrity(get_or_create_wallet(user))["ok"] is True


def test_an_automatic_refund_never_follows_a_delivered_code(
    user, auth, catalog, funded_wallet
):
    from apps.orders.models import RefundReason
    from apps.orders.services import issue_refund

    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)
    order = drive(Order.objects.get(reference=buy(client).data["reference"]), seconds=30)
    balance = get_or_create_wallet(user).balance

    # Force a status an automatic refund would normally accept.
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.EXPIRED)
    order.refresh_from_db()
    issue_refund(order, reason=RefundReason.NO_CODE_RECEIVED, automatic=True)

    assert get_or_create_wallet(user).balance == balance
    assert not Refund.objects.filter(order=order).exists()


# ---------------------------------------------------------------------------
# Staff are told
# ---------------------------------------------------------------------------


def test_a_failed_order_alerts_staff_in_app_every_time_and_by_email_once(
    user, auth, catalog, funded_wallet, admin_user, support_user
):
    from django.core import mail

    from apps.notifications.models import Channel, Notification

    verification_mock.force_scenario("PROVIDER_ERR")
    funded_wallet(user, "200.00")
    client = auth(user)
    first = Order.objects.get(reference=buy(client).data["reference"])
    buy(client)

    alerts = Notification.objects.filter(event="STAFF_ORDER_FAILED")
    # Those who can refund; support (view only) and the customer are not paged.
    assert set(alerts.values_list("user_id", flat=True)) == {admin_user.pk}
    assert alerts.filter(channel=Channel.IN_APP).count() == 2
    # Two failures together are one email, not two.
    assert alerts.filter(channel=Channel.EMAIL).count() == 1
    sent = [m for m in mail.outbox if "didn't go through" in m.subject]
    assert len(sent) == 1 and sent[0].to == [admin_user.email]

    alert = alerts.filter(channel=Channel.IN_APP).order_by("created_at").first()
    assert first.reference in alert.title
    assert "refunded" in alert.body
    assert user.email not in alert.body  # masked, even for staff
    assert alert.metadata["admin_link"] == f"/admin/orders?q={first.reference}"


def test_a_purchase_confirmation_email_goes_through_brevo(user, auth, catalog, funded_wallet,
                                                         brevo):
    verification_mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)
    order = Order.objects.get(reference=buy(client).data["reference"])
    drive(order, seconds=30)

    with _capture_on_commit(execute=True):
        complete = client.post(f"/api/v1/orders/{order.reference}/complete/", {}, format="json")
    assert complete.status_code == 200

    completed = [c["json"] for c in brevo.calls if "completed" in c["json"]["subject"].lower()]
    assert completed and completed[-1]["to"] == [{"email": user.email}]
    assert order.service.name in completed[-1]["textContent"]
