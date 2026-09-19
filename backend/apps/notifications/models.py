from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class NotificationEvent(models.TextChoices):
    ACCOUNT_CREATED = "ACCOUNT_CREATED", "Account created"
    PAYMENT_SUCCESSFUL = "PAYMENT_SUCCESSFUL", "Payment successful"
    PAYMENT_FAILED = "PAYMENT_FAILED", "Payment failed"
    PURCHASE_SUCCESSFUL = "PURCHASE_SUCCESSFUL", "Purchase successful"
    NUMBER_ASSIGNED = "NUMBER_ASSIGNED", "Number assigned"
    CODE_RECEIVED = "CODE_RECEIVED", "Verification code received"
    ORDER_COMPLETED = "ORDER_COMPLETED", "Order completed"
    ORDER_EXPIRED = "ORDER_EXPIRED", "Order expired"
    REFUND_ISSUED = "REFUND_ISSUED", "Refund issued"
    SECURITY_ALERT = "SECURITY_ALERT", "Security alert"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED", "Account suspended"
    ADMIN_MESSAGE = "ADMIN_MESSAGE", "Message from support"


class Channel(models.TextChoices):
    IN_APP = "IN_APP", "In-app"
    EMAIL = "EMAIL", "Email"
    # Registered now so the abstraction is real rather than aspirational;
    # no delivery backend is wired up for these yet.
    SMS = "SMS", "SMS"
    WHATSAPP = "WHATSAPP", "WhatsApp"


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class Notification(BaseModel):
    """An in-app notification, and the record of any out-of-app delivery.

    Verification codes are never stored in a notification body - the message
    says a code arrived and links to the order, where the code is shown subject
    to the provider agreement.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.CharField(max_length=32, choices=NotificationEvent.choices, db_index=True)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=400, blank=True, default="")

    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    delivery_status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    delivery_error = models.CharField(max_length=255, blank=True, default="")

    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "read_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event} -> {self.user_id}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])
