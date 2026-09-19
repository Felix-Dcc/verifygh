"""Run the real user journeys and read every log line they produce.

Unit tests of the redaction patterns (test_logging.py) prove the filter works
on strings we thought of. This proves it on what the application actually
emits: the production JSON formatter and filters are attached at DEBUG, the
flows run, and the captured output is searched for anything secret.
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone

from apps.common.logging import JsonFormatter, RedactingFilter, RequestContextFilter
from apps.orders.models import Order, OrderStatus

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
NEW_PASSWORD = "Another-Horse-Battery-7"
MOCK_SECRET = "canary-mock-secret-for-logs-4411"


@pytest.fixture
def captured():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(JsonFormatter())
    handler.setLevel(logging.DEBUG)

    loggers = [logging.getLogger(), logging.getLogger("verifygh"), logging.getLogger("django")]
    saved = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
    yield stream
    for lg, level in saved:
        lg.removeHandler(handler)
        lg.setLevel(level)


def test_the_main_journeys_log_nothing_secret(captured, api, user, catalog, settings):
    from apps.orders.services import poll_order
    from apps.payments import mock as payment_mock
    from apps.verification import mock as verification_mock

    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS,
                                    "mock": {"secret_key": MOCK_SECRET}}
    secrets_seen: dict[str, str] = {"password": PASSWORD, "new password": NEW_PASSWORD,
                                    "mock secret": MOCK_SECRET}

    # A failed login, then a real one.
    api.post("/api/v1/auth/login/", {"email": user.email, "password": "Wrong-Password-1"},
             format="json")
    response = api.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD},
                        format="json")
    api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    secrets_seen["csrf"] = response.data["csrf_token"]
    secrets_seen["access"] = api.cookies[settings.AUTH_COOKIE_ACCESS].value
    secrets_seen["refresh"] = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    # Deposit, confirmed by a signed webhook.
    deposit = api.post("/api/v1/payments/deposit/",
                       {"amount": "100.00", "phone": "0241234567"}, format="json")
    assert deposit.status_code == 201, deposit.data
    raw, headers = payment_mock.build_webhook(reference=deposit.data["reference"],
                                              amount="100.00")
    api.post("/api/v1/payments/webhooks/mock/", data=raw, content_type="application/json",
             HTTP_X_MOCK_SIGNATURE=headers["X-Mock-Signature"])
    secrets_seen["webhook signature"] = headers["X-Mock-Signature"]

    # Buy a number and receive a code.
    verification_mock.force_scenario("HAPPY")
    order_response = api.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                              format="json")
    assert order_response.status_code == 201, order_response.data
    order = Order.objects.get(reference=order_response.data["reference"])
    from apps.orders.services import fulfil_order

    fulfil_order(order)
    order.refresh_from_db()
    verification_mock.fast_forward(order.provider_order_id, 60)
    order = poll_order(order)
    api.get(f"/api/v1/orders/{order.reference}/")
    api.get(f"/api/v1/orders/{order.reference}/status/")
    assert order.verification_code, order.status
    secrets_seen["verification code"] = order.verification_code
    secrets_seen["rented number"] = order.phone_number

    # Rotate, change password, sign out.
    api.post("/api/v1/auth/refresh/", {}, format="json")
    secrets_seen["rotated refresh"] = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.post("/api/v1/auth/password/change/",
             {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json")
    api.post("/api/v1/auth/logout/", {}, format="json")

    output = captured.getvalue()
    assert "order_created" in output, "capture is not wired to the application loggers"

    leaks = [name for name, value in secrets_seen.items() if value and value in output]
    assert not leaks, f"logs contain: {leaks}"
    for phone in ("+233241234567", "0241234567", "233241234567"):
        assert phone not in output, f"logs contain the full customer number {phone}"
    assert "eyJ" not in output, "a JWT reached the logs"


def test_an_exception_carrying_a_token_is_redacted(captured):
    logger = logging.getLogger("verifygh.test")
    token = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiMTIzIn0.c2lnbmF0dXJlLXZhbHVl"
    try:
        raise ValueError(f"upstream rejected Authorization: Bearer {token} for +233241234567")
    except ValueError:
        logger.exception("provider_call_failed")

    output = captured.getvalue()
    assert token not in output
    assert "+233241234567" not in output


def test_stored_unreadable_webhooks_are_scrubbed(api, settings):
    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS,
                                    "mock": {"secret_key": MOCK_SECRET}}
    from apps.payments.mock import sign
    from apps.payments.models import PaymentWebhookEvent

    raw = b'not json: customer +233241234567 paid, token=abc123secret'
    api.post("/api/v1/payments/webhooks/mock/", data=raw, content_type="application/json",
             HTTP_X_MOCK_SIGNATURE=sign(raw))

    stored = str(PaymentWebhookEvent.objects.get(event_type="unparsed").payload)
    assert "+233241234567" not in stored
    assert "abc123secret" not in stored


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _finished_order(user, catalog, funded_wallet, *, age_days: int, status=OrderStatus.COMPLETED):
    from apps.orders.services import create_order

    funded_wallet(user, "100.00")
    order = create_order(user=user, service_slug="instagram", country_code="US",
                         idempotency_key=f"retention-{age_days}-{status}")
    Order.objects.filter(pk=order.pk).update(
        status=status, verification_code="482913", verification_message="Your code is 482913",
        code_received_at=timezone.now(), created_at=timezone.now() - timedelta(days=age_days),
    )
    return Order.objects.get(pk=order.pk)


def test_old_verification_codes_are_erased(user, catalog, funded_wallet):
    from apps.orders.tasks import purge_verification_data

    old = _finished_order(user, catalog, funded_wallet, age_days=45)
    recent = _finished_order(user, catalog, funded_wallet, age_days=3)
    active = _finished_order(user, catalog, funded_wallet, age_days=45,
                             status=OrderStatus.CODE_RECEIVED)

    assert purge_verification_data() == 1

    old.refresh_from_db()
    recent.refresh_from_db()
    active.refresh_from_db()
    assert old.verification_code == "" and old.verification_message == ""
    assert old.code_received_at is not None  # the refund policy still sees delivery
    assert old.price > Decimal("0")  # the financial record is untouched
    assert recent.verification_code == "482913"
    assert active.verification_code == "482913"


def test_retention_is_scheduled(settings_obj=settings):
    from config.celery import app

    tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert "apps.orders.tasks.purge_verification_data" in tasks
