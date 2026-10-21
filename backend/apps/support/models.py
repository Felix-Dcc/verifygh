"""Support chat: one ongoing thread per customer, answered by staff holding
SUPPORT_CHAT."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class ThreadStatus(models.TextChoices):
    #: Only threads from before the chat went human-only.
    BOT = "BOT", "With the bot"
    WAITING = "WAITING", "Waiting for staff"
    ANSWERED = "ANSWERED", "Answered"
    CLOSED = "CLOSED", "Closed"


class Sender(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    #: Notes the system writes, such as "This chat was closed".
    BOT = "BOT", "Bot"
    STAFF = "STAFF", "Staff"


class ChatThread(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_thread"
    )
    status = models.CharField(max_length=10, choices=ThreadStatus.choices,
                              default=ThreadStatus.WAITING, db_index=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "support_chat_thread"
        ordering = ["-last_message_at"]


class ChatMessage(BaseModel):
    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=Sender.choices)
    #: Which staff member wrote it; null for customer and bot messages.
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    body = models.TextField(blank=True)
    #: A photo the customer attached. Kept in the database (there is no
    #: persistent disk) and served only to that customer and to admins.
    image = models.BinaryField(null=True, editable=False)
    image_type = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        db_table = "support_chat_message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["thread", "created_at"])]
