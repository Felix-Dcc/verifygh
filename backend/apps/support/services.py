"""The support chat: customers write, admins holding SUPPORT_CHAT reply.

Every message a customer sends goes to the admins; there is no bot. Codes and
phone numbers are masked before a message is saved, so a pasted verification
code never sits in the chat log.
"""

from __future__ import annotations

import re

from django.db import transaction

from apps.accounts.constants import AdminPermission
from apps.common.errors import ValidationFailed
from apps.common.logging import redact_text
from apps.notifications.services import notify
from apps.notifications.staff import alert_staff
from apps.numbers.services import read_evidence
from apps.support.models import ChatMessage, ChatThread, Sender, ThreadStatus

# A pasted verification code (4-8 digits, maybe split by a space or dash) never
# reaches the chat log. Not after a letter or dash, so VGH-123456 survives.
_CODE = re.compile(r"(?<![\w-])\d{2,4}[ -]?\d{2,4}(?![\w-])")


def clean(text: str) -> str:
    text = redact_text(text.strip())
    return _CODE.sub(
        lambda m: "[code hidden]" if 4 <= len(re.sub(r"\D", "", m[0])) <= 8 else m[0], text
    )


def _add(thread: ChatThread, sender: str, body: str, staff=None, image=None) -> ChatMessage:
    data, content_type = image or (None, "")
    message = ChatMessage.objects.create(thread=thread, sender=sender, body=body, staff=staff,
                                         image=data, image_type=content_type)
    thread.last_message_at = message.created_at
    return message


@transaction.atomic
def customer_message(user, *, body: str = "", image=None) -> ChatThread:
    """`image` is an uploaded file; checked the same way as other screenshots."""
    photo = read_evidence([image], required=False)[0] if image else None
    body = clean(body)
    if not body and photo is None:
        raise ValidationFailed("Write a message or attach a photo.")

    thread, created = ChatThread.objects.select_for_update().get_or_create(user=user)
    _add(thread, Sender.CUSTOMER, body, image=photo)
    if created or thread.status != ThreadStatus.WAITING:
        thread.status = ThreadStatus.WAITING
        # Once per wait: the next alert comes after an admin has replied or closed it.
        alert_staff(
            permission=AdminPermission.SUPPORT_CHAT, event="STAFF_CHAT_WAITING",
            title="A customer sent a support message", body="Open the chat in the admin to reply.",
            link=f"/admin/chats?thread={thread.id}", reference=str(thread.id),
            cooldown_key=f"support-chat-alert:{thread.id}", cooldown_seconds=1800,
        )
    thread.save(update_fields=["status", "last_message_at", "updated_at"])
    return thread


@transaction.atomic
def staff_reply(thread: ChatThread, staff, body: str) -> None:
    thread = ChatThread.objects.select_for_update().get(pk=thread.pk)
    _add(thread, Sender.STAFF, clean(body), staff=staff)
    thread.status = ThreadStatus.ANSWERED
    thread.save(update_fields=["status", "last_message_at", "updated_at"])
    notify(thread.user, event="SUPPORT_REPLY", title="Support replied to your message",
           body="Open the chat to read the reply.", metadata={"support_chat": True})


@transaction.atomic
def close(thread: ChatThread) -> None:
    thread = ChatThread.objects.select_for_update().get(pk=thread.pk)
    _add(thread, Sender.BOT, "This chat was closed. Write again any time.")
    thread.status = ThreadStatus.CLOSED
    thread.save(update_fields=["status", "last_message_at", "updated_at"])
