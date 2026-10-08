"""Base models shared across the project."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True


class ImmutableModel(BaseModel):
    """A row that may be created but never updated.

    Used for the wallet ledger and audit log. Enforced in application code; the
    accompanying DB-level protection is that nothing in the codebase issues an
    UPDATE against these tables, and the integrity checker recomputes from them.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self._state.adding is False:
            raise ValueError(
                f"{self.__class__.__name__} rows are immutable and cannot be updated."
            )
        return super().save(*args, **kwargs)


class MaintenanceMode(models.TextChoices):
    OFF = "OFF", "Open"
    BUYING_PAUSED = "BUYING_PAUSED", "Buying paused"
    #: The payment provider is down, the number provider is fine: customers
    #: keep buying with the balance they have (8 Oct 2026, Paystack disabled).
    DEPOSITS_PAUSED = "DEPOSITS_PAUSED", "Top-ups paused"
    ALL_PAUSED = "ALL_PAUSED", "Buying and top-ups paused"


class MaintenanceState(TimeStampedModel):
    """Site-wide maintenance: one row (pk=1), seeded by its migration.

    Pausing closes the till - new orders and number reuse, and with ALL_PAUSED
    new top-ups too. Nothing already under way stops: an order waiting for its
    code is still polled and refunded if none comes, a deposit the customer is
    approving on their phone is still credited, webhooks and the admin work.
    See apps/common/maintenance.py.
    """

    mode = models.CharField(max_length=20, choices=MaintenanceMode.choices,
                            default=MaintenanceMode.OFF)
    #: Shown to customers while paused. Blank: the default notice.
    message = models.CharField(max_length=300, blank=True)
    #: Why staff paused it - one of the presets, or their own words.
    reason = models.CharField(max_length=300, blank=True)
    since = models.DateTimeField(null=True, blank=True)
    #: Manual MoMo top-ups (apps/payments/manual.py): customers send money to
    #: the business wallet and staff credit it after seeing it arrive.
    manual_deposits = models.BooleanField(default=False)
    #: Shown to customers only. Nothing reopens the site by itself.
    expected_back_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "common_maintenance_state"

    def __str__(self) -> str:
        return f"Maintenance [{self.mode}]"
