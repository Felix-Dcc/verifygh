"""Support chat: the bot, the hand-off to admins, and who can read what."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.support.models import ChatMessage, ChatThread, ThreadStatus

pytestmark = pytest.mark.django_db

CHAT = "/api/v1/support/chat/"
INBOX = "/api/v1/admin/chats/"


@pytest.fixture
def staff(auth):
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
    assert api.post(CHAT, {"topic": "refunds"}, format="json").status_code == 401


def test_an_empty_chat_offers_the_topics(user, auth):
    data = auth(user).get(CHAT).data
    assert data["status"] == ThreadStatus.BOT
    assert data["messages"] == []
    assert {"key": "human", "label": "Talk to a person"} in data["topics"]


def test_a_topic_gets_the_bot_answer(user, auth):
    data = auth(user).post(CHAT, {"topic": "code"}, format="json").data
    assert [m["sender"] for m in data["messages"]] == ["CUSTOMER", "BOT"]
    assert "2 minutes" in data["messages"][1]["body"]


def test_typed_words_match_a_topic_or_fall_back(user, auth):
    client = auth(user)
    data = client.post(CHAT, {"body": "How do I top up with MoMo?"}, format="json").data
    assert "Add funds" in data["messages"][-1]["body"]
    data = client.post(CHAT, {"body": "hello there"}, format="json").data
    assert "Talk to a person" in data["messages"][-1]["body"]


def test_body_or_topic_is_required_and_bounded(user, auth):
    client = auth(user)
    assert client.post(CHAT, {}, format="json").status_code == 400
    assert client.post(CHAT, {"topic": "nope"}, format="json").status_code == 400
    assert client.post(CHAT, {"body": "x" * 1001}, format="json").status_code == 400


def test_pasted_codes_and_phone_numbers_never_reach_the_log(user, auth):
    auth(user).post(CHAT, {"body": "my code 482913 and 123-456 for +12025550123 on VGH-123456"},
                    format="json")
    body = ChatMessage.objects.get(sender="CUSTOMER").body
    assert "482913" not in body and "123-456" not in body and "2025550123" not in body
    assert "VGH-123456" in body


def test_my_orders_shows_only_my_orders_and_no_costs(
    user, other_user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks
):
    from apps.verification import mock

    mock.force_scenario("HAPPY")
    for account in (user, other_user):
        funded_wallet(account)
    with django_capture_on_commit_callbacks(execute=True):
        theirs = APIClient()
        response = theirs.post("/api/v1/auth/login/", {"email": other_user.email,
                                                       "password": "Correct-Horse-Battery-2"},
                               format="json")
        theirs.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
        theirs.post("/api/v1/orders/", {"service": "instagram", "country": "US"}, format="json")
        mine = auth(user)
        mine.post("/api/v1/orders/", {"service": "instagram", "country": "US"}, format="json")

    answer = mine.post(CHAT, {"topic": "my_orders"}, format="json").data["messages"][-1]["body"]
    my_order = Order.objects.get(user=user)
    their_order = Order.objects.get(user=other_user)
    assert my_order.reference in answer and their_order.reference not in answer
    assert f"{my_order.price:,.2f}" in answer
    assert str(my_order.provider_cost) not in answer
    if my_order.verification_code:
        assert my_order.verification_code not in answer
    assert my_order.phone_number[-7:] not in answer


def test_wallet_balance_is_the_customers_own(user, auth, funded_wallet):
    funded_wallet(user, "42.50")
    answer = auth(user).post(CHAT, {"topic": "wallet"}, format="json").data["messages"][-1]["body"]
    assert "GH₵ 42.50" in answer


def test_hand_off_alerts_admins_only_and_staff_reply_reaches_the_customer(
    user, auth, staff, django_capture_on_commit_callbacks
):
    support, admin = staff(Role.SUPPORT), staff(Role.ADMIN)
    with django_capture_on_commit_callbacks(execute=True):
        data = auth(user).post(CHAT, {"topic": "human"}, format="json").data
    assert data["status"] == ThreadStatus.WAITING
    alerted = set(Notification.objects.filter(event="STAFF_CHAT_WAITING")
                  .values_list("user__role", flat=True))
    assert alerted == {Role.ADMIN}

    # Typed messages now go to staff: no bot reply.
    customer = auth(user)
    data = customer.post(CHAT, {"body": "my refund never came"}, format="json").data
    assert data["messages"][-1]["sender"] == "CUSTOMER"

    thread = ChatThread.objects.get(user=user)
    assert support.get(INBOX).status_code == 403
    listing = admin.get(INBOX).data["results"]
    assert listing[0]["id"] == str(thread.id) and listing[0]["status"] == "WAITING"

    detail = admin.post(f"{INBOX}{thread.id}/reply/", {"body": "Looking now, code 556677?"},
                        format="json").data
    assert detail["status"] == ThreadStatus.ANSWERED
    assert "556677" not in detail["messages"][-1]["body"]
    assert Notification.objects.filter(user=user, event="SUPPORT_REPLY").exists()
    assert customer.get(CHAT).data["messages"][-1]["sender"] == "STAFF"

    assert admin.post(f"{INBOX}{thread.id}/close/").data["status"] == ThreadStatus.CLOSED
    # Writing again after a close goes back to the bot.
    data = customer.post(CHAT, {"topic": "refunds"}, format="json").data
    assert data["status"] == ThreadStatus.BOT


def test_customers_cannot_open_the_inbox(user, other_user, auth):
    client = auth(user)
    client.post(CHAT, {"topic": "human"}, format="json")
    assert client.get(INBOX).status_code == 403
    thread = ChatThread.objects.get(user=user)
    assert client.get(f"{INBOX}{thread.id}/").status_code == 403


def test_sending_is_rate_limited(user, auth):
    client = auth(user)
    codes = [client.post(CHAT, {"topic": "refunds"}, format="json").status_code
             for _ in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429
    # Polling is not counted against the send limit.
    assert client.get(CHAT).status_code == 200
