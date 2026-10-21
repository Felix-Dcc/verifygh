"""The support chat: a rule-based bot answers first, staff take over on request.

The bot never reaches beyond the signed-in customer's own rows, and only ever
shows what the customer already sees in the app: references, statuses, the
price they paid. Never provider costs, codes or phone numbers.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from apps.accounts.constants import AdminPermission
from apps.common.logging import redact_text
from apps.notifications.services import notify
from apps.notifications.staff import alert_staff
from apps.support.models import ChatMessage, ChatThread, Sender, ThreadStatus

HUMAN = "human"

#: Topic key -> (button label, answer). Account topics are answered from data.
TOPICS: dict[str, tuple[str, str]] = {
    "code": ("Code not arriving", (
        "Most codes arrive within 2 minutes, so wait at least that long before cancelling. "
        "Telegram, Instagram, TikTok and Signal fail more often than other apps. "
        "If no code arrives before the number expires, the full price goes back to your "
        "wallet automatically, and you can cancel for a refund any time before a code arrives. "
        "WhatsApp numbers stay open for 60 minutes. Open the order to see tips for your app."
    )),
    "refunds": ("Refunds", (
        "Refunds are automatic: if no code arrives, or you cancel before one does, the full "
        "price goes back to your wallet straight away. If a service says the number is "
        "already used, open the order and choose Report a problem. We review it and replace "
        "or refund the number where our policy allows."
    )),
    "rentals": ("Rentals", (
        "A rented number receives messages until its end time, shown on the rental page. "
        "It never renews by itself: open the rental and extend it before it ends to keep it. "
        "Choose My rentals to see how long yours have left."
    )),
    "deposits": ("Adding money (MoMo)", (
        "Go to Wallet and choose Add funds, then pay with MTN MoMo, Telecel Cash or AT Money. "
        "Your balance updates once the network confirms, usually within a minute. If it has "
        "not, choose Check again on the Add funds screen. Never share your MoMo PIN with "
        "anyone, including us."
    )),
    "my_orders": ("My orders", ""),
    "my_rentals": ("My rentals", ""),
    "wallet": ("My balance", ""),
    HUMAN: ("Talk to a person", ""),
}

_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (HUMAN, ("human", "person", "agent", "admin", "staff", "someone")),
    ("my_rentals", ("my rental", "time left")),
    ("my_orders", ("my order", "order status")),
    ("wallet", ("balance", "my wallet")),
    ("refunds", ("refund", "money back", "reverse")),
    ("deposits", ("deposit", "momo", "top up", "top-up", "topup", "add funds", "mobile money",
                  "paid but", "telecel", "airteltigo")),
    ("rentals", ("rent", "extend", "renew")),
    ("code", ("code", "otp", "sms", "not coming", "not arriving", "didn't get", "didnt get",
              "no message", "whatsapp", "telegram", "tiktok", "instagram", "signal")),
]

FALLBACK = (
    "Sorry, I didn't catch that. Choose a topic below, or choose Talk to a person and an "
    "admin will reply here."
)

# A pasted verification code (4-8 digits, maybe split by a space or dash) never
# reaches the chat log. Not after a letter or dash, so VGH-123456 survives.
_CODE = re.compile(r"(?<![\w-])\d{2,4}[ -]?\d{2,4}(?![\w-])")


def clean(text: str) -> str:
    text = redact_text(text.strip())
    return _CODE.sub(
        lambda m: "[code hidden]" if 4 <= len(re.sub(r"\D", "", m[0])) <= 8 else m[0], text
    )


def match_topic(text: str) -> str | None:
    lowered = text.lower()
    for topic, words in _KEYWORDS:
        if any(word in lowered for word in words):
            return topic
    return None


def _cedis(amount) -> str:
    return f"GH₵ {amount:,.2f}"


def _left(ends_at) -> str:
    seconds = int((ends_at - timezone.now()).total_seconds())
    if seconds <= 0:
        return "ending now"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days} day{'s' if days != 1 else ''} {hours} h left"
    return f"{hours} h {rest // 60} min left" if hours else f"{rest // 60} min left"


def account_answer(user, topic: str) -> str:
    """The customer's own data: only rows belonging to the signed-in user."""
    if topic == "my_orders":
        orders = list(user.orders.select_related("service").order_by("-created_at")[:3])
        if not orders:
            return "You have no orders yet. Choose Buy a number to get started."
        lines = [f"{o.reference} · {o.service.name} · {o.get_status_display()} · {_cedis(o.price)}"
                 for o in orders]
        return "Your latest orders:\n" + "\n".join(lines) + "\nOpen Orders for the details."
    if topic == "my_rentals":
        from apps.rentals.models import OPEN_RENTAL_STATUSES

        rentals = list(user.rentals.select_related("service")
                       .filter(status__in=OPEN_RENTAL_STATUSES).order_by("ends_at")[:3])
        if not rentals:
            return "You have no active rentals. Choose Rent a number to get one."
        lines = [f"{r.reference} · {r.service.name if r.service else 'Any app'} · "
                 f"{r.get_status_display()} · {_left(r.ends_at) if r.ends_at else 'starting'}"
                 for r in rentals]
        return "Your active rentals:\n" + "\n".join(lines) + "\nOpen a rental to extend it."
    if topic == "wallet":
        from apps.wallet.services import get_or_create_wallet

        wallet = get_or_create_wallet(user)
        text = f"Your balance is {_cedis(wallet.balance)}."
        if wallet.promo_balance:
            text += f" You also have {_cedis(wallet.promo_balance)} promotional credit."
        return text
    raise ValueError(topic)


def _add(thread: ChatThread, sender: str, body: str, staff=None) -> ChatMessage:
    message = ChatMessage.objects.create(thread=thread, sender=sender, body=body, staff=staff)
    thread.last_message_at = message.created_at
    return message


def _hand_off(thread: ChatThread) -> None:
    alert_staff(
        permission=AdminPermission.SUPPORT_CHAT, event="STAFF_CHAT_WAITING",
        title="A customer wants to chat", body="Open the chat in the admin to reply.",
        link=f"/admin/chats?thread={thread.id}", reference=str(thread.id),
        cooldown_key=f"support-chat-alert:{thread.id}", cooldown_seconds=1800,
    )


@transaction.atomic
def customer_message(user, *, body: str = "", topic: str = "") -> ChatThread:
    thread, _ = ChatThread.objects.select_for_update().get_or_create(user=user)
    if thread.status == ThreadStatus.CLOSED:
        thread.status = ThreadStatus.BOT
    with_staff = thread.status in (ThreadStatus.WAITING, ThreadStatus.ANSWERED)

    if topic:
        _add(thread, Sender.CUSTOMER, TOPICS[topic][0])
    else:
        _add(thread, Sender.CUSTOMER, clean(body))
        # Once a person has the chat, typed messages are for them, not the bot.
        topic = HUMAN if with_staff else (match_topic(body) or "")

    if topic == HUMAN:
        if thread.status != ThreadStatus.WAITING:
            thread.status = ThreadStatus.WAITING
            _hand_off(thread)
        if not with_staff:
            _add(thread, Sender.BOT, "I've passed this chat to our team. An admin will reply "
                 "here as soon as they can, and you'll get a notification. You can keep "
                 "writing in the meantime. Never send your password or MoMo PIN.")
    elif topic:
        _add(thread, Sender.BOT, TOPICS[topic][1] or account_answer(user, topic))
    else:
        _add(thread, Sender.BOT, FALLBACK)

    thread.save(update_fields=["status", "last_message_at", "updated_at"])
    return thread


@transaction.atomic
def staff_reply(thread: ChatThread, staff, body: str) -> None:
    thread = ChatThread.objects.select_for_update().get(pk=thread.pk)
    _add(thread, Sender.STAFF, clean(body), staff=staff)
    thread.status = ThreadStatus.ANSWERED
    thread.save(update_fields=["status", "last_message_at", "updated_at"])
    notify(thread.user, event="SUPPORT_REPLY", title="Support replied to your chat",
           body="Open the chat to read the reply.", metadata={"support_chat": True})


@transaction.atomic
def close(thread: ChatThread) -> None:
    thread = ChatThread.objects.select_for_update().get(pk=thread.pk)
    _add(thread, Sender.BOT, "This chat was closed. Write again any time.")
    thread.status = ThreadStatus.CLOSED
    thread.save(update_fields=["status", "last_message_at", "updated_at"])
