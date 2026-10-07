"""Staff correcting an email address a user mistyped at registration.

A user wrote in: "I made a mistake when entering my email so I want to rectify
it." Their address was never verified, so they could not fix it themselves.

Allowed only while the address is unverified. Verification tokens belong to the
account, not to an address, so the danger is the links already sent to the
wrong address: they must stop working, or whoever owns that address could
verify - or reset the password of - an account that is not theirs.
"""

from __future__ import annotations

import re

import pytest
from django.core import mail

from apps.accounts.constants import Role
from apps.accounts.models import SecurityToken, TokenPurpose, User
from apps.accounts.services import EMAIL_ALREADY_VERIFIED
from apps.audit.models import AdminAction

pytestmark = pytest.mark.django_db

ADMIN_PASSWORD = "Correct-Horse-Battery-3"
USER_PASSWORD = "Correct-Horse-Battery-1"
WRONG = "kwame@gmial.com"
RIGHT = "kwame@gmail.com"

_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _on_commit
    _on_commit = django_capture_on_commit_callbacks
    yield
    _on_commit = None


@pytest.fixture
def mistyped(db):
    """Registered with a typo; never verified."""
    return User.objects.create_user(email=WRONG, password=USER_PASSWORD, full_name="Kwame")


@pytest.fixture
def staff(admin_user, auth):
    return auth(admin_user, ADMIN_PASSWORD)


def change(client, target, new=RIGHT, confirm=None, reason="User reported a typo at signup"):
    body = {"new_email": new, "confirm_email": new if confirm is None else confirm,
            "reason": reason}
    with _on_commit(execute=True):
        return client.post(f"/api/v1/admin/users/{target.pk}/change-email/", body,
                           format="json")


def link_token(message) -> str:
    match = re.search(r"/verify-email/([A-Za-z0-9_\-]+)", message.body)
    assert match, message.body
    return match.group(1)


# -- the correction -----------------------------------------------------------


def test_an_unverified_email_is_corrected_and_a_new_link_sent(staff, mistyped, admin_user):
    mail.outbox.clear()
    response = change(staff, mistyped)
    assert response.status_code == 200, response.data
    assert response.data["email"] == RIGHT
    assert response.data["is_email_verified"] is False

    mistyped.refresh_from_db()
    assert mistyped.email == RIGHT
    assert mistyped.is_email_verified is False and mistyped.email_verified_at is None

    assert [m.to for m in mail.outbox] == [[RIGHT]]  # nothing to the wrong address
    action = AdminAction.objects.get(action="ADMIN_CHANGED_UNVERIFIED_EMAIL")
    assert action.admin == admin_user
    assert action.target_id == str(mistyped.pk)
    assert action.before["email"] == WRONG and action.after["email"] == RIGHT
    assert action.reason == "User reported a typo at signup"


def test_the_new_link_verifies_the_new_address(staff, mistyped, api):
    mail.outbox.clear()
    change(staff, mistyped)
    token = link_token(mail.outbox[-1])
    from rest_framework.test import APIClient

    response = APIClient().post("/api/v1/auth/email/verify/confirm/", {"token": token},
                                format="json")
    assert response.status_code == 200, response.data
    mistyped.refresh_from_db()
    assert mistyped.email == RIGHT and mistyped.is_email_verified is True


def test_a_link_sent_to_the_wrong_address_no_longer_works(staff, mistyped):
    from rest_framework.test import APIClient

    from apps.accounts.services import send_verification_email

    mail.outbox.clear()
    send_verification_email(mistyped)
    old = link_token(mail.outbox[-1])
    assert mail.outbox[-1].to == [WRONG]

    change(staff, mistyped)
    response = APIClient().post("/api/v1/auth/email/verify/confirm/", {"token": old},
                                format="json")
    assert response.status_code == 400
    mistyped.refresh_from_db()
    assert mistyped.is_email_verified is False


def test_a_password_reset_sent_to_the_wrong_address_no_longer_works(staff, mistyped):
    from apps.accounts.services import request_password_reset

    request_password_reset(WRONG)
    reset = SecurityToken.objects.get(user=mistyped, purpose=TokenPurpose.PASSWORD_RESET)
    assert reset.used_at is None

    change(staff, mistyped)
    reset.refresh_from_db()
    assert reset.used_at is not None


def test_sessions_end_and_the_user_signs_in_with_the_new_email(staff, mistyped, auth):
    from rest_framework.test import APIClient

    user_client = APIClient()
    login = user_client.post("/api/v1/auth/login/", {"email": WRONG, "password": USER_PASSWORD},
                             format="json")
    assert login.status_code == 200
    change(staff, mistyped)

    assert user_client.get("/api/v1/auth/me/").status_code == 401
    again = APIClient().post("/api/v1/auth/login/", {"email": RIGHT, "password": USER_PASSWORD},
                             format="json")
    assert again.status_code == 200
    assert APIClient().post("/api/v1/auth/login/", {"email": WRONG, "password": USER_PASSWORD},
                            format="json").status_code == 401


def test_the_address_is_normalised(staff, mistyped):
    response = change(staff, mistyped, new="  Kwame@GMAIL.com ", confirm="kwame@gmail.com")
    assert response.status_code == 200, response.data
    mistyped.refresh_from_db()
    assert mistyped.email == RIGHT


# -- refusals -------------------------------------------------------------------


def test_a_verified_email_cannot_be_changed(staff, user):
    response = change(staff, user)
    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMAIL_ALREADY_VERIFIED"
    assert response.data["error"]["message"] == EMAIL_ALREADY_VERIFIED
    user.refresh_from_db()
    assert user.email == "kwame@example.com"
    assert not AdminAction.objects.filter(action="ADMIN_CHANGED_UNVERIFIED_EMAIL").exists()


def test_an_address_another_account_uses_is_refused(staff, mistyped, user):
    response = change(staff, mistyped, new="KWAME@example.com")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMAIL_TAKEN"
    mistyped.refresh_from_db()
    assert mistyped.email == WRONG


@pytest.mark.parametrize("new,confirm,reason", [
    ("not-an-email", "not-an-email", "Typo at signup"),
    (RIGHT, "someone@else.com", "Typo at signup"),
    (WRONG, WRONG, "Typo at signup"),
    (RIGHT, RIGHT, ""),
])
def test_bad_requests_change_nothing(staff, mistyped, new, confirm, reason):
    response = change(staff, mistyped, new=new, confirm=confirm, reason=reason)
    assert response.status_code == 400
    mistyped.refresh_from_db()
    assert mistyped.email == WRONG


def test_support_staff_cannot_change_emails(support_user, auth, mistyped):
    response = change(auth(support_user, "Correct-Horse-Battery-4"), mistyped)
    assert response.status_code == 403
    mistyped.refresh_from_db()
    assert mistyped.email == WRONG


def test_customers_cannot_change_emails(user, auth, mistyped):
    assert change(auth(user, USER_PASSWORD), mistyped).status_code == 403


def test_an_admin_cannot_change_another_admins_email(db, auth, mistyped):
    admin = User.objects.create_user(email="ops@verifygh.local", password=ADMIN_PASSWORD,
                                     role=Role.ADMIN, is_email_verified=True)
    other = User.objects.create_user(email="ops2@verifygh.local", password=ADMIN_PASSWORD,
                                     role=Role.ADMIN)
    response = change(auth(admin, ADMIN_PASSWORD), other, new="ops3@verifygh.local")
    assert response.status_code == 409
    other.refresh_from_db()
    assert other.email == "ops2@verifygh.local"


def test_a_queued_email_goes_to_the_current_address(mistyped):
    """A task that loaded the user before the correction still mails the right
    address - never a live link to the old one."""
    from apps.accounts.services import send_verification_email

    stale = User.objects.get(pk=mistyped.pk)  # loaded before the change
    User.objects.filter(pk=mistyped.pk).update(email=RIGHT)
    mail.outbox.clear()
    send_verification_email(stale)
    assert mail.outbox[-1].to == [RIGHT]
