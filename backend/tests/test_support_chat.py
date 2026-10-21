"""Support chat: customers write, admins reply, and who can read what."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.support.models import ChatMessage, ChatThread, ThreadStatus

pytestmark = pytest.mark.django_db

CHAT = "/api/v1/support/chat/"
INBOX = "/api/v1/admin/chats/"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def photo(data: bytes = PNG, name: str = "shot.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="image/png")


@pytest.fixture
def staff(db):
    """Sign in a fresh client as a staff member of `role`."""

    def _staff(role: str) -> APIClient:
        account = User.objects.create_user(
            email=f"{role.lower()}@verifygh.local", password="Correct-Horse-Battery-9",
            role=role, is_email_verified=True,
        )
        client = APIClient()
        response = client.post("/api/v1/auth/login/", {"email": account.email,
                                                        "password": "Correct-Horse-Battery-9"},
                               format="json")
        client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
        return client

    return _staff


def test_chat_needs_a_signed_in_customer(api):
    assert api.get(CHAT).status_code == 401
    assert api.post(CHAT, {"body": "hi"}, format="json").status_code == 401


def test_an_empty_chat(user, auth):
    data = auth(user).get(CHAT).data
    assert data == {"status": ThreadStatus.WAITING, "messages": []}


def test_a_message_goes_to_admins_with_no_bot_reply(
    user, auth, staff, django_capture_on_commit_callbacks
):
    staff(Role.SUPPORT)
    staff(Role.ADMIN)
    with django_capture_on_commit_callbacks(execute=True):
        data = auth(user).post(CHAT, {"body": "My deposit is still pending"},
                               format="json").data
    assert data["status"] == ThreadStatus.WAITING
    assert [m["sender"] for m in data["messages"]] == ["CUSTOMER"]
    alerted = set(Notification.objects.filter(event="STAFF_CHAT_WAITING")
                  .values_list("user__role", flat=True))
    assert alerted == {Role.ADMIN}


def test_admins_are_alerted_once_per_wait(user, auth, django_capture_on_commit_callbacks,
                                          staff):
    staff(Role.ADMIN)
    client = auth(user)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(CHAT, {"body": "hello"}, format="json")
        client.post(CHAT, {"body": "anyone?"}, format="json")
    assert Notification.objects.filter(event="STAFF_CHAT_WAITING", channel="IN_APP").count() == 1


def test_a_message_needs_text_or_a_photo_and_is_bounded(user, auth):
    client = auth(user)
    assert client.post(CHAT, {}, format="json").status_code == 400
    assert client.post(CHAT, {"body": "   "}, format="json").status_code == 400
    assert client.post(CHAT, {"body": "x" * 1001}, format="json").status_code == 400


def test_pasted_codes_and_phone_numbers_never_reach_the_log(user, auth):
    auth(user).post(CHAT, {"body": "my code 482913 and 123-456 for +12025550123 on VGH-123456"},
                    format="json")
    body = ChatMessage.objects.get(sender="CUSTOMER").body
    assert "482913" not in body and "123-456" not in body and "2025550123" not in body
    assert "VGH-123456" in body


def test_a_photo_is_stored_and_served_only_to_its_owner_and_admins(
    user, other_user, auth, staff
):
    client = auth(user)
    response = client.post(CHAT, {"body": "see this", "image": photo()}, format="multipart")
    assert response.status_code == 201
    sent = response.data["messages"][-1]
    assert sent["has_image"] is True and "image" not in sent

    url = f"{CHAT}images/{sent['id']}/"
    served = client.get(url)
    assert served.status_code == 200 and served.content == PNG
    assert served["Content-Type"] == "image/png"
    assert served["X-Content-Type-Options"] == "nosniff"

    intruder = APIClient()
    login = intruder.post("/api/v1/auth/login/", {"email": other_user.email,
                                                  "password": "Correct-Horse-Battery-2"},
                          format="json")
    intruder.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])
    assert intruder.get(url).status_code == 404

    thread = ChatThread.objects.get(user=user)
    admin_url = f"{INBOX}{thread.id}/images/{sent['id']}/"
    admin = staff(Role.ADMIN)
    assert admin.get(admin_url).content == PNG
    assert staff(Role.SUPPORT).get(admin_url).status_code == 403
    assert admin.get(INBOX).data["results"][0]["preview"] == "see this"


def test_a_photo_alone_is_a_message(user, auth):
    response = auth(user).post(CHAT, {"image": photo()}, format="multipart")
    assert response.status_code == 201
    assert response.data["messages"][-1]["body"] == ""


def test_only_real_images_are_accepted(user, auth):
    client = auth(user)
    fake = photo(b"<script>alert(1)</script>", "shot.png")
    assert client.post(CHAT, {"image": fake}, format="multipart").status_code == 400
    big = photo(PNG + b"\x00" * (5 * 1024 * 1024))
    assert client.post(CHAT, {"image": big}, format="multipart").status_code == 400
    assert not ChatMessage.objects.exists()


def test_staff_reply_reaches_the_customer_and_close_reopens_on_next_message(
    user, auth, staff
):
    customer = auth(user)
    customer.post(CHAT, {"body": "my refund never came"}, format="json")
    thread = ChatThread.objects.get(user=user)
    admin = staff(Role.ADMIN)
    assert staff(Role.SUPPORT).get(INBOX).status_code == 403
    listing = admin.get(INBOX).data["results"]
    assert listing[0]["id"] == str(thread.id) and listing[0]["status"] == "WAITING"

    detail = admin.post(f"{INBOX}{thread.id}/reply/", {"body": "Looking now, code 556677?"},
                        format="json").data
    assert detail["status"] == ThreadStatus.ANSWERED
    assert "556677" not in detail["messages"][-1]["body"]
    assert Notification.objects.filter(user=user, event="SUPPORT_REPLY").exists()
    assert customer.get(CHAT).data["messages"][-1]["sender"] == "STAFF"

    assert admin.post(f"{INBOX}{thread.id}/close/").data["status"] == ThreadStatus.CLOSED
    data = customer.post(CHAT, {"body": "one more thing"}, format="json").data
    assert data["status"] == ThreadStatus.WAITING


def test_customers_cannot_open_the_inbox(user, auth):
    client = auth(user)
    client.post(CHAT, {"body": "hi"}, format="json")
    assert client.get(INBOX).status_code == 403
    thread = ChatThread.objects.get(user=user)
    assert client.get(f"{INBOX}{thread.id}/").status_code == 403


def test_sending_is_rate_limited(user, auth):
    client = auth(user)
    codes = [client.post(CHAT, {"body": "hello"}, format="json").status_code
             for _ in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429
    # Polling is not counted against the send limit.
    assert client.get(CHAT).status_code == 200
