"""Base models shared across the project."""

from __future__ import annotations

import uuid

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
