"""The 6-digit email code: typed into the app right after "Create account".

10 Oct 2026: verification links were not being clicked (or opened in the
wrong browser), so every account is now asked for a code before anything else.
The link stays in the same email as a fallback.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import EmailVerificationCode, SecurityToken, TokenPurpose, User
from apps.accounts.services import send_verification_email

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
STATUS = "/api/v1/auth/email/verify/status/"
SEND = "/api/v1/auth/email/verify/send/"
CODE = "/api/v1/auth/email/verify/code/"
CHANGE = "/api/v1/auth/email/change/"
CONFIRM_LINK = "/api/v1/auth/email/verify/confirm/"


@pytest.fixture
def newcomer(db) -> User:
    return User.objects.create_user(email="ama@gmail.com", password=PASSWORD,
                                    full_name="Ama Owusu")


def code_from_last_email() -> str:
    """The code as the customer reads it: from the email they received."""
    match = re.search(r"^\s{4}(\d{6})\s*$", mail.outbox[-1].body, re.MULTILINE)
    assert match, mail.outbox[-1].body
    return match.group(1)


def link_token_from_last_email() -> str:
    return re.search(r"/verify-email/([A-Za-z0-9_\-]+)", mail.outbox[-1].body).group(1)


def cool_down():
    past = timezone.now() - timedelta(minutes=5)
    EmailVerificationCode.objects.update(created_at=past)
    User.objects.update(created_at=past)


def emailed(user) -> str:
    cool_down()
    assert send_verification_email(user)
    return code_from_last_email()


# -- the code -----------------------------------------------------------------


def test_the_code_in_the_email_verifies_the_account(newcomer, auth):
    from apps.audit.models import AuditLog

    code = emailed(newcomer)
    response = auth(newcomer).post(CODE, {"code": code}, format="json")

    assert response.status_code == 200, response.data
    newcomer.refresh_from_db()
    assert newcomer.is_email_verified and newcomer.email_verified_at
    assert response.data["user"]["is_email_verified"] is True
    assert AuditLog.objects.filter(action="EMAIL_VERIFIED", metadata__method="code").exists()
    # Every other link and code still in the inbox is retired.
    assert not SecurityToken.objects.filter(user=newcomer, used_at__isnull=True,
                                            purpose=TokenPurpose.EMAIL_VERIFICATION).exists()
    assert not EmailVerificationCode.objects.filter(user=newcomer,
                                                    used_at__isnull=True).exists()


def test_the_code_is_never_stored_or_sent_in_the_clear(newcomer):
    from apps.notifications.models import Notification

    code = emailed(newcomer)
    row = EmailVerificationCode.objects.get(user=newcomer, used_at__isnull=True)
    assert code not in row.code_hash
    assert row.code_hash == EmailVerificationCode.hash_code(newcomer.pk, code)
    assert code not in mail.outbox[-1].subject
    for note in Notification.objects.filter(user=newcomer):
        assert code not in note.title and code not in note.body


def test_a_wrong_code_says_how_many_tries_are_left(newcomer, auth):
    emailed(newcomer)
    client = auth(newcomer)
    response = client.post(CODE, {"code": "000000" if code_from_last_email() != "000000"
                                  else "111111"}, format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "INVALID_CODE"
    assert "4 tries left" in response.data["error"]["message"]
    newcomer.refresh_from_db()
    assert newcomer.is_email_verified is False


def test_five_wrong_tries_kill_the_code(newcomer, auth):
    code = emailed(newcomer)
    wrong = "000000" if code != "000000" else "111111"
    client = auth(newcomer)
    for _ in range(5):
        client.post(CODE, {"code": wrong}, format="json")
    response = client.post(CODE, {"code": code}, format="json")   # even the right one now
    assert response.status_code == 400
    assert response.data["error"]["code"] == "CODE_EXPIRED"
    newcomer.refresh_from_db()
    assert newcomer.is_email_verified is False


def test_an_expired_code_is_refused(newcomer, auth):
    code = emailed(newcomer)
    EmailVerificationCode.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    response = auth(newcomer).post(CODE, {"code": code}, format="json")
    assert response.status_code == 400 and response.data["error"]["code"] == "CODE_EXPIRED"


def test_a_new_code_replaces_the_last_one(newcomer, auth):
    first = emailed(newcomer)
    second = emailed(newcomer)
    client = auth(newcomer)
    if first != second:
        assert client.post(CODE, {"code": first}, format="json").status_code == 400
    assert client.post(CODE, {"code": second}, format="json").status_code == 200


def test_one_accounts_code_never_verifies_another(newcomer, auth, db, monkeypatch):
    other = User.objects.create_user(email="kofi@gmail.com", password=PASSWORD)
    codes = iter([123456, 654321])
    monkeypatch.setattr("apps.accounts.models.secrets.randbelow", lambda n: next(codes))
    assert emailed(newcomer) == "123456"
    assert emailed(other) == "654321"

    response = auth(other).post(CODE, {"code": "123456"}, format="json")
    assert response.status_code == 400 and response.data["error"]["code"] == "INVALID_CODE"
    other.refresh_from_db()
    newcomer.refresh_from_db()
    assert other.is_email_verified is False and newcomer.is_email_verified is False


def test_the_link_in_the_same_email_still_works(newcomer, api):
    emailed(newcomer)
    response = api.post(CONFIRM_LINK, {"token": link_token_from_last_email()}, format="json")
    assert response.status_code == 200
    newcomer.refresh_from_db()
    assert newcomer.is_email_verified


def test_the_code_endpoint_needs_a_session(newcomer, api):
    code = emailed(newcomer)
    assert api.post(CODE, {"code": code}, format="json").status_code in (401, 403)


# -- sending ------------------------------------------------------------------


def test_registration_emails_a_code(api, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post("/api/v1/auth/register/", {
            "email": "esi@gmail.com", "password": PASSWORD, "full_name": "Esi Mensah",
            "accepted_terms": True}, format="json")
    assert response.status_code == 201, response.data
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["esi@gmail.com"]
    assert re.fullmatch(r"\d{6}", code_from_last_email())
    assert EmailVerificationCode.objects.filter(user__email="esi@gmail.com",
                                                used_at__isnull=True).count() == 1


def test_a_new_account_does_not_get_a_second_email_from_the_app(newcomer, auth):
    """The sign-up email is on its way: the verify screen must not send another."""
    status = auth(newcomer).get(STATUS).data
    assert status["code_active"] is True and status["resend_in"] > 0
    response = auth(newcomer).post(SEND, {}, format="json")
    assert response.status_code == 200 and response.data["sent"] is False
    assert mail.outbox == []


def test_resend_waits_45_seconds_then_sends(newcomer, auth):
    emailed(newcomer)
    mail.outbox.clear()
    EmailVerificationCode.objects.update(created_at=timezone.now())
    client = auth(newcomer)
    again = client.post(SEND, {}, format="json")
    assert again.status_code == 200 and again.data["sent"] is False and again.data["resend_in"] > 0
    assert mail.outbox == []
    cool_down()
    later = client.post(SEND, {}, format="json")
    assert later.status_code == 200 and later.data["sent"] is True
    assert len(mail.outbox) == 1


def test_an_older_unverified_account_gets_a_code_when_it_asks(newcomer, auth):
    cool_down()   # signed up days ago, never verified, no code yet
    client = auth(newcomer)
    status = client.get(STATUS).data
    assert status["code_active"] is False and status["resend_in"] == 0
    assert client.post(SEND, {}, format="json").data["sent"] is True
    assert re.fullmatch(r"\d{6}", code_from_last_email())


# -- correcting the address ---------------------------------------------------


def test_an_unverified_user_corrects_their_own_address(newcomer, auth):
    from apps.audit.models import AuditLog

    old_code = emailed(newcomer)
    old_link = link_token_from_last_email()
    client = auth(newcomer)
    response = client.post(CHANGE, {"new_email": "Ama.Owusu@gmail.com", "password": PASSWORD},
                           format="json")
    assert response.status_code == 200, response.data
    newcomer.refresh_from_db()
    assert newcomer.email == "ama.owusu@gmail.com" and newcomer.is_email_verified is False
    assert mail.outbox[-1].to == ["ama.owusu@gmail.com"]
    assert AuditLog.objects.filter(action="EMAIL_SELF_CHANGED").exists()
    # What went to the old address is dead; the new code works.
    new_code = code_from_last_email()
    if old_code != new_code:
        assert client.post(CODE, {"code": old_code}, format="json").status_code == 400
    assert client.post(CONFIRM_LINK, {"token": old_link}, format="json").status_code == 400
    assert client.post(CODE, {"code": new_code}, format="json").status_code == 200


def test_correcting_the_address_needs_the_password(newcomer, auth):
    response = auth(newcomer).post(CHANGE, {"new_email": "x@gmail.com", "password": "wrong-one"},
                                   format="json")
    assert response.status_code == 400
    newcomer.refresh_from_db()
    assert newcomer.email == "ama@gmail.com"


def test_a_verified_address_cannot_be_changed_this_way(user, auth):
    response = auth(user).post(CHANGE, {"new_email": "x@gmail.com", "password": PASSWORD},
                               format="json")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMAIL_ALREADY_VERIFIED"


def test_an_address_in_use_cannot_be_taken(newcomer, auth, db):
    User.objects.create_user(email="taken@gmail.com", password=PASSWORD)
    response = auth(newcomer).post(CHANGE, {"new_email": "taken@gmail.com",
                                            "password": PASSWORD}, format="json")
    assert response.status_code == 409 and response.data["error"]["code"] == "EMAIL_TAKEN"


def test_three_corrections_at_most(newcomer, auth):
    client = auth(newcomer)
    for n in range(3):
        cool_down()
        assert client.post(CHANGE, {"new_email": f"ama{n}@gmail.com", "password": PASSWORD},
                           format="json").status_code == 200
    cool_down()
    response = client.post(CHANGE, {"new_email": "ama9@gmail.com", "password": PASSWORD},
                           format="json")
    assert response.status_code == 409 and response.data["error"]["code"] == "EMAIL_CHANGE_LIMIT"


def test_a_staff_correction_cancels_the_old_code_too(newcomer, admin_user):
    from apps.accounts.services import admin_change_unverified_email

    emailed(newcomer)
    admin_change_unverified_email(user=newcomer, new_email="ama.right@gmail.com",
                                  reason="Customer asked", actor=admin_user)
    assert not EmailVerificationCode.objects.filter(
        user=newcomer, used_at__isnull=True, created_at__lt=timezone.now() - timedelta(minutes=1),
    ).exists()


# -- what an unverified account can do ---------------------------------------


def test_top_ups_wait_for_a_verified_email(newcomer, auth, settings):
    from apps.payments.models import Payment

    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    response = auth(newcomer).post("/api/v1/payments/deposit/", {
        "amount": "10.00", "phone": "0241234567", "network": "MTN"}, format="json")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "EMAIL_NOT_VERIFIED"
    assert not Payment.objects.exists()


def test_a_verified_account_can_top_up(user, auth, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    response = auth(user).post("/api/v1/payments/deposit/", {
        "amount": "10.00", "phone": "0241234567", "network": "MTN"}, format="json")
    assert response.status_code == 201, response.data
    assert Decimal(response.data["amount"]) == Decimal("10.00")


# -- the admin ----------------------------------------------------------------


def test_the_admin_filters_verified_and_unverified_accounts(newcomer, user, admin_user):
    from rest_framework.test import APIClient

    staff = APIClient()
    login = staff.post("/api/v1/auth/login/", {"email": admin_user.email,
                                               "password": "Correct-Horse-Battery-3"},
                       format="json")
    staff.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])

    def emails(flag):
        rows = staff.get("/api/v1/admin/users/", {"verified": flag, "page_size": 100}).data
        return {row["email"] for row in rows["results"]}

    assert newcomer.email in emails("false") and user.email not in emails("false")
    assert user.email in emails("true") and newcomer.email not in emails("true")
