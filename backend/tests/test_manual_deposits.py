"""Manual MoMo top-ups, while no gateway can collect (8 Oct 2026).

Customers send money to the business wallet and claim it with the transaction
ID and a screenshot; staff credit it only after seeing it arrive, by the
receiving wallet's transaction ID - which can settle one top-up, ever.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AdminAction
from apps.common.models import MaintenanceState
from apps.payments.models import Payment, PaymentStatus
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "Correct-Horse-Battery-3"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def image(name="proof.png", body=PNG):
    return SimpleUploadedFile(name, body, content_type="image/png")


@pytest.fixture(autouse=True)
def manual_on(settings, db):
    settings.VERIFYGH = {**settings.VERIFYGH, "MANUAL_DEPOSIT_NUMBER": "0560636182",
                         "MANUAL_DEPOSIT_MAX": "200.00", "MANUAL_DEPOSIT_DAILY_LIMIT": "400.00",
                         "MANUAL_DEPOSIT_MAX_OPEN": 2}
    MaintenanceState.objects.update_or_create(pk=1, defaults={"manual_deposits": True})


def start(client, amount="50.00"):
    return client.post("/api/v1/payments/manual/", {"amount": amount}, format="json")


def claim(client, reference, txn="ABC123456", body=PNG, phone="0241234567", network="MTN"):
    return client.post(f"/api/v1/payments/{reference}/manual-claim/", {
        "sender_phone": phone, "network": network, "transaction_id": txn,
        "evidence": image(body=body)}, format="multipart")


def approve(staff, reference, amount="50.00", receipt="ATM9988776655"):
    return staff.post(f"/api/v1/admin/manual-deposits/{reference}/approve/",
                      {"amount_received": amount, "receipt_id": receipt}, format="json")


@pytest.fixture
def staff(admin_user, auth):
    from rest_framework.test import APIClient

    client = APIClient()
    login = client.post("/api/v1/auth/login/", {"email": admin_user.email,
                                                "password": ADMIN_PASSWORD}, format="json")
    client.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])
    return client


# -- the customer -----------------------------------------------------------------


def test_the_deposit_page_shows_the_manual_option(api):
    manual = api.get("/api/v1/payments/options/").data["manual"]
    assert manual["enabled"] is True and manual["number"] == "0560636182"
    assert manual["ussd"] == "*246#"


def test_switched_off_it_is_hidden_and_refused(user, auth):
    MaintenanceState.objects.filter(pk=1).update(manual_deposits=False)
    client = auth(user)
    assert client.get("/api/v1/payments/options/").data["manual"]["enabled"] is False
    assert start(client).status_code == 503


def test_a_claim_goes_to_review_and_credits_nothing(user, auth):
    client = auth(user)
    reference = start(client).data["reference"]
    response = claim(client, reference)
    assert response.status_code == 200, response.data
    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.PROCESSING and payment.expires_at is None
    assert payment.evidence.count() == 1
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_a_screenshot_is_required(user, auth):
    client = auth(user)
    reference = start(client).data["reference"]
    response = client.post(f"/api/v1/payments/{reference}/manual-claim/", {
        "sender_phone": "0241234567", "network": "MTN", "transaction_id": "ABC123456"},
        format="multipart")
    assert response.status_code == 400


def test_only_images_are_accepted(user, auth):
    client = auth(user)
    reference = start(client).data["reference"]
    response = claim(client, reference, body=b"%PDF-1.4 not an image")
    assert response.status_code == 400


def test_a_transaction_id_cannot_be_claimed_twice(user, auth):
    client = auth(user)
    first = start(client, "20.00").data["reference"]
    second = start(client, "20.00").data["reference"]
    assert claim(client, first, txn="SAME123").status_code == 200
    response = claim(client, second, txn="same123", body=PNG + b"different")
    assert response.status_code == 409


def test_the_same_screenshot_cannot_be_reused(user, auth):
    client = auth(user)
    first = start(client, "20.00").data["reference"]
    second = start(client, "20.00").data["reference"]
    assert claim(client, first, txn="TXN0001").status_code == 200
    assert claim(client, second, txn="TXN0002").status_code == 409


def test_limits_hold(user, auth):
    client = auth(user)
    assert start(client, "500.00").status_code == 400          # over the per-top-up max
    start(client, "100.00")
    start(client, "100.00")
    assert start(client, "10.00").status_code == 429           # two already open


# -- staff ------------------------------------------------------------------------


def test_approval_credits_what_arrived_once(user, auth, staff, admin_user):
    client = auth(user)
    reference = start(client, "50.00").data["reference"]
    claim(client, reference)

    response = approve(staff, reference, amount="45.00")
    assert response.status_code == 200, response.data
    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.SUCCESS
    assert get_or_create_wallet(user).balance == Decimal("45.00")  # what arrived, not claimed
    assert payment.metadata["claimed_amount"] == "50.00"
    assert AdminAction.objects.filter(action="MANUAL_DEPOSIT_APPROVE", admin=admin_user).exists()

    assert approve(staff, reference, amount="45.00").status_code == 409  # decided already
    assert get_or_create_wallet(user).balance == Decimal("45.00")


def test_one_wallet_receipt_settles_one_top_up(user, auth, staff):
    client = auth(user)
    first = start(client, "20.00").data["reference"]
    second = start(client, "20.00").data["reference"]
    claim(client, first, txn="TXNA001")
    claim(client, second, txn="TXNB002", body=PNG + b"other")
    assert approve(staff, first, "20.00", receipt="ATM111").status_code == 200
    response = approve(staff, second, "20.00", receipt="atm111")
    assert response.status_code == 409
    assert get_or_create_wallet(user).balance == Decimal("20.00")


def test_rejection_tells_the_customer_and_credits_nothing(user, auth, staff):
    from apps.notifications.models import Notification

    client = auth(user)
    reference = start(client).data["reference"]
    claim(client, reference)
    response = staff.post(f"/api/v1/admin/manual-deposits/{reference}/reject/",
                          {"reason": "We could not find this payment on our wallet."},
                          format="json")
    assert response.status_code == 200
    assert Payment.objects.get(reference=reference).status == PaymentStatus.FAILED
    assert Notification.objects.filter(user=user, event="PAYMENT_FAILED").exists()
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_the_queue_shows_claims_with_their_screenshots(user, auth, staff):
    client = auth(user)
    reference = start(client).data["reference"]
    claim(client, reference)
    queue = staff.get("/api/v1/admin/manual-deposits/").data
    row = queue["waiting"][0]
    assert row["reference"] == reference and row["transaction_id"] == "ABC123456"
    shot_id = row["evidence"][0]["id"]
    shot = staff.get(f"/api/v1/admin/manual-deposits/{reference}/evidence/{shot_id}/")
    assert shot.status_code == 200 and shot["Content-Type"] == "image/png"
    assert shot["X-Content-Type-Options"] == "nosniff"


def test_customers_cannot_approve_or_see_the_queue(user, auth):
    client = auth(user)
    reference = start(client).data["reference"]
    claim(client, reference)
    assert client.get("/api/v1/admin/manual-deposits/").status_code == 403
    assert approve(client, reference).status_code == 403
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_support_can_see_but_not_approve(support_user, user, auth):
    from rest_framework.test import APIClient

    reference = start(auth(user)).data["reference"]
    support = APIClient()
    login = support.post("/api/v1/auth/login/", {"email": support_user.email,
                                                 "password": "Correct-Horse-Battery-4"},
                         format="json")
    support.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])
    assert support.get("/api/v1/admin/manual-deposits/").status_code == 200
    assert approve(support, reference).status_code == 403


def test_the_sweeps_leave_manual_top_ups_alone(user, auth):
    from apps.payments.tasks import expire_stale_payments, reconcile_recent_payments

    client = auth(user)
    reference = start(client).data["reference"]
    claim(client, reference)
    reconcile_recent_payments()
    expire_stale_payments()
    assert Payment.objects.get(reference=reference).status == PaymentStatus.PROCESSING


def test_staff_switch_it_on_and_off(staff):
    response = staff.post("/api/v1/admin/manual-deposits/settings/",
                          {"enabled": False, "reason": "Moolre is live"}, format="json")
    assert response.status_code == 200 and response.data["enabled"] is False
    assert AdminAction.objects.filter(action="MANUAL_DEPOSITS_OFF").exists()
