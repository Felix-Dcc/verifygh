from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, ImmutableModel


class AuditLog(ImmutableModel):
    """Append-only record of everything that changed state.

    Written for both user actions and system actions. Rows are never updated or
    deleted by application code; `ImmutableModel.save` raises on update.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_email = models.CharField(max_length=254, blank=True, default="")
    action = models.CharField(max_length=64, db_index=True)

    target_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    target_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    request_id = models.CharField(max_length=32, blank=True, default="", db_index=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_email or 'system'}"


class AdminAction(ImmutableModel):
    """A privileged action, with the mandatory reason attached.

    Wallet adjustments, refunds, suspensions and pricing changes all land here.
    `reason` is not nullable by design: an unexplained balance change is exactly
    the thing an audit is meant to catch.
    """

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="admin_actions"
    )
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=64, db_index=True)
    reason = models.TextField()
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "audit_admin_action"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["admin", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.action} on {self.target_type}:{self.target_id}"


class SuspicionLevel(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class SuspiciousActivity(BaseModel):
    """An abuse signal awaiting review.

    Signals are advisory: they never auto-suspend an account. A human decides,
    and that decision is itself recorded as an AdminAction.
    """

    class Kind(models.TextChoices):
        SHARED_DEVICE = "SHARED_DEVICE", "One device across many accounts"
        RAPID_ORDERS = "RAPID_ORDERS", "Unusually rapid ordering"
        HIGH_FAILURE_RATE = "HIGH_FAILURE_RATE", "High order failure rate"
        DEPOSIT_ANOMALY = "DEPOSIT_ANOMALY", "Unusual deposit pattern"
        MULTIPLE_FAILED_LOGINS = "MULTIPLE_FAILED_LOGINS", "Repeated failed logins"
        REFUND_ABUSE = "REFUND_ABUSE", "Repeated refund requests"
        VELOCITY_LIMIT = "VELOCITY_LIMIT", "Velocity limit reached"
        TOKEN_REUSE = "TOKEN_REUSE", "Rotated refresh token replayed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="suspicious_activities",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    level = models.CharField(
        max_length=8, choices=SuspicionLevel.choices, default=SuspicionLevel.LOW, db_index=True
    )
    description = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)

    resolved = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_flags",
    )
    resolution_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "audit_suspicious_activity"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["resolved", "level", "-created_at"]),
            models.Index(fields=["user", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} ({self.level})"
