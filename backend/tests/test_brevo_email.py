"""Transactional email through Brevo: the backend, the flows that use it, failures.

No email is sent. The `brevo` fixture (conftest.py) puts the real Brevo
backend in place and fakes Brevo's API underneath it, recording every request.
"""

from __future__ import annotations

import logging
import re

import pytest
import requests
from django.core import mail
from django.core.mail import EmailMultiAlternatives

from apps.accounts.models import User
from apps.notifications.brevo import API_URL, BrevoEmailBackend, BrevoError
from apps.notifications.models import DeliveryStatus, Notification

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
CONFIRM = "/api/v1/auth/email/verify/confirm/"
RESET = "/api/v1/auth/password/reset/"
RESET_CONFIRM = "/api/v1/auth/password/reset/confirm/"
LOGIN = "/api/v1/auth/login/"
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(autouse=True)
def _commit_hooks(django_capture_on_commit_callbacks):
    global _capture
    _capture = django_capture_on_commit_callbacks
    yield


def register(api, email="abena@gmail.com"):
    with _capture(execute=True):
        return api.post(REGISTER, {"email": email, "password": PASSWORD, "full_name": "Abena",
                                   "accepted_terms": True}, format="json")


def link_token(payload: dict, path: str) -> str:
    match = re.search(rf"{path}([A-Za-z0-9_\-]+)", payload["textContent"])
    assert match, payload["textContent"]
    return match.group(1)


class _Records(logging.Handler):
    """Collects log records, extras included - the app's loggers do not propagate."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def text(self) -> str:
        return " ".join(f"{r.getMessage()} {r.__dict__}" for r in self.records)


# ---------------------------------------------------------------------------
# The request Brevo receives
# ---------------------------------------------------------------------------


def test_registration_sends_the_verification_email_through_brevo(api, brevo):
    response = register(api)
    assert response.status_code == 201, response.data

    (call,) = brevo.calls
    assert call["url"] == API_URL == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "xkeysib-test-key-not-real"
    assert call["timeout"]
    body = call["json"]
    assert body["sender"] == {"email": "support@getverifygh.com", "name": "VerifyGH"}
    assert body["to"] == [{"email": "abena@gmail.com"}]
    assert body["subject"] == "Verify your VerifyGH email address"
    # Both parts, the same link in each, in the branded layout.
    token = link_token(body, "/verify-email/")
    assert token in body["htmlContent"]
    assert "Verify Email" in body["htmlContent"] and "/icons/icon-192.png" in body["htmlContent"]
    assert "support@getverifygh.com" in body["htmlContent"]
    assert Notification.objects.get(channel="EMAIL").delivery_status == DeliveryStatus.SENT


def test_the_link_from_the_brevo_email_verifies_that_account_only(api, brevo):
    register(api)
    other = register(api, "kofi@gmail.com")
    assert other.status_code == 201
    token = link_token(brevo.calls[0]["json"], "/verify-email/")

    assert api.post(CONFIRM, {"token": token}, format="json").status_code == 200
    assert User.objects.get(email="abena@gmail.com").is_email_verified is True
    assert User.objects.get(email="kofi@gmail.com").is_email_verified is False
    # Used once, used up.
    assert api.post(CONFIRM, {"token": token}, format="json").status_code == 400


def test_password_reset_works_end_to_end_through_brevo(api, brevo, user):
    with _capture(execute=True):
        assert api.post(RESET, {"email": user.email}, format="json").status_code == 200
    (call,) = brevo.calls
    payload = call["json"]
    assert payload["to"] == [{"email": user.email}]
    assert "Reset password" in payload["htmlContent"]
    token = link_token(payload, r"/reset-password\?token=")

    new_password = "A-Brand-New-Passphrase-7"
    response = api.post(RESET_CONFIRM, {"token": token, "new_password": new_password},
                        format="json")
    assert response.status_code == 200, response.data
    assert api.post(LOGIN, {"email": user.email, "password": new_password},
                    format="json").status_code == 200


def test_a_security_alert_goes_through_brevo(api, auth, user, brevo):
    client = auth(user)
    with _capture(execute=True):
        response = client.post("/api/v1/auth/password/change/", {
            "current_password": "Correct-Horse-Battery-1",
            "new_password": "Another-Long-Passphrase-3"}, format="json")
    assert response.status_code == 200, response.data
    subjects = [c["json"]["subject"] for c in brevo.calls]
    assert any("password was changed" in s.lower() for s in subjects), subjects
    alert = next(c["json"] for c in brevo.calls
                 if "password was changed" in c["json"]["subject"].lower())
    # No template of its own: the message's text in the shared layout.
    assert "Your VerifyGH password was just changed." in alert["htmlContent"]


# ---------------------------------------------------------------------------
# The backend on its own
# ---------------------------------------------------------------------------


def message(**overrides) -> EmailMultiAlternatives:
    fields = {"subject": "Hello", "body": "Line one\n\nLine <two>",
              "from_email": '"VerifyGH" <support@getverifygh.com>', "to": ["a@b.co"]}
    fields.update(overrides)
    return EmailMultiAlternatives(**fields)


def test_plain_text_gets_a_safe_html_part_because_brevo_requires_one(brevo):
    BrevoEmailBackend().send_messages([message()])
    body = brevo.calls[0]["json"]
    assert body["textContent"] == "Line one\n\nLine <two>"
    assert "<p>Line one</p>" in body["htmlContent"]
    assert "&lt;two&gt;" in body["htmlContent"]  # escaped, never injected


def test_reply_to_cc_and_display_names_are_passed_on(brevo):
    BrevoEmailBackend().send_messages([message(
        to=['"Ama Owusu" <ama@b.co>'], cc=["c@b.co"], reply_to=["help@getverifygh.com"])])
    body = brevo.calls[0]["json"]
    assert body["to"] == [{"email": "ama@b.co", "name": "Ama Owusu"}]
    assert body["cc"] == [{"email": "c@b.co"}]
    assert body["replyTo"] == {"email": "help@getverifygh.com"}


@pytest.mark.parametrize(("reply", "says", "retryable"), [
    ((401, {"code": "unauthorized", "message": "Key not found"}), "API key", False),
    ((401, {"code": "unauthorized", "message": "unrecognised IP address"}), "Authorised IPs",
     False),
    ((400, {"code": "invalid_parameter", "message": "Sender support@x.com is not valid"}),
     "sender", False),
    ((400, {"code": "invalid_parameter", "message": "email is not valid in to"}),
     "refused the email", False),
    ((402, {"code": "not_enough_credits", "message": "Not enough credits"}), "credits", False),
    ((429, {"code": "too_many_requests", "message": "Rate limit"}), "rate-limiting", True),
    ((503, {}), "server error", True),
])
def test_every_brevo_refusal_becomes_a_clear_internal_error(brevo, reply, says, retryable):
    brevo.replies.append(reply)
    with pytest.raises(BrevoError) as raised:
        BrevoEmailBackend().send_messages([message()])
    assert says.lower() in str(raised.value).lower()
    assert raised.value.retryable is retryable
    assert "xkeysib" not in str(raised.value)


@pytest.mark.parametrize("failure", [requests.Timeout("slow"), requests.ConnectionError("dns")])
def test_timeouts_and_network_failures_are_retryable(brevo, failure):
    brevo.replies.append(failure)
    with pytest.raises(BrevoError) as raised:
        BrevoEmailBackend().send_messages([message()])
    assert raised.value.retryable is True


def test_without_an_api_key_nothing_is_called(brevo, settings):
    settings.BREVO_API_KEY = ""
    with pytest.raises(BrevoError) as raised:
        BrevoEmailBackend().send_messages([message()])
    assert raised.value.code == "not_configured"
    assert brevo.calls == []
    assert BrevoEmailBackend(fail_silently=True).send_messages([message()]) == 0


def test_an_addressless_recipient_is_refused_before_calling_brevo(brevo):
    with pytest.raises(BrevoError):
        BrevoEmailBackend().send_messages([message(to=["not an address"])])
    assert brevo.calls == []


# ---------------------------------------------------------------------------
# A failure never breaks the flow that sent the email
# ---------------------------------------------------------------------------


def test_brevo_down_still_registers_and_records_the_failure(api, brevo):
    brevo.replies.extend([(500, {"message": "boom"})] * 5)
    response = register(api)

    assert response.status_code == 201, response.data
    account = User.objects.get(email="abena@gmail.com")
    assert account.is_email_verified is False  # nothing bypasses verification
    notification = Notification.objects.get(channel="EMAIL")
    assert notification.delivery_status == DeliveryStatus.FAILED
    assert "server error" in notification.delivery_error


def test_an_unverified_sender_is_logged_for_staff_without_the_key_or_address(api, brevo):
    brevo.replies.append(
        (400, {"code": "invalid_parameter",
               "message": "Sender support@getverifygh.com is not valid for abena@gmail.com"}))
    handler = _Records()
    app_logger = logging.getLogger("verifygh")
    app_logger.addHandler(handler)
    try:
        register(api)
    finally:
        app_logger.removeHandler(handler)

    logged = handler.text()
    assert "brevo_email_refused" in logged
    assert "sender" in logged.lower()
    assert "xkeysib-test-key-not-real" not in logged
    assert "abena@gmail.com" not in logged
    notification = Notification.objects.get(channel="EMAIL")
    assert "not verified in Brevo" in notification.delivery_error


def test_the_test_suite_sends_nothing_by_default():
    """Without the fixture, mail goes to Django's in-memory outbox - never Brevo."""
    from django.conf import settings

    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    assert isinstance(mail.outbox, list)
