from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.catalog.models import Country, Service
from apps.common.models import BaseModel, TimeStampedModel


class ExchangeRate(TimeStampedModel):
    """A point-in-time FX rate.

    Rates are append-only: a new rate is a new row, never an edit. Every quote
    records which row it used, so a price can always be explained after the fact
    even once the rate has moved.

    The primary key is a plain auto-increment rather than a UUID, deliberately.
    "Latest rate" must be a total order, and timestamps are not: on a coarse
    system clock two rates written in the same tick share a `fetched_at`, and
    ordering by it alone picks one at random. The id breaks that tie monotonically.
    """

    base_currency = models.CharField(max_length=3, default="USD")
    quote_currency = models.CharField(max_length=3, default="GHS")
    rate = models.DecimalField(max_digits=16, decimal_places=6)
    source = models.CharField(
        max_length=32, default="manual", help_text="manual, or the rate provider key."
    )
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "pricing_exchange_rate"
        ordering = ["-fetched_at", "-id"]
        indexes = [
            models.Index(fields=["base_currency", "quote_currency", "-fetched_at", "-id"]),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(rate__gt=0), name="exchange_rate_positive"),
        ]

    def __str__(self) -> str:
        return f"1 {self.base_currency} = {self.rate} {self.quote_currency}"


class MarkupType(models.TextChoices):
    PERCENTAGE = "PERCENTAGE", "Percentage"
    FIXED = "FIXED", "Fixed amount"
    HYBRID = "HYBRID", "Percentage plus fixed"


class Rounding(models.TextChoices):
    NONE = "NONE", "No rounding"
    NEAREST_0_10 = "NEAREST_0_10", "Nearest 0.10"
    NEAREST_0_50 = "NEAREST_0_50", "Nearest 0.50"
    NEAREST_1_00 = "NEAREST_1_00", "Nearest 1.00"
    CEIL_1_00 = "CEIL_1_00", "Round up to 1.00"


class PricingRule(BaseModel):
    """How a provider cost becomes a customer price.

    Resolution is most-specific-first: a rule for (service, country) beats one
    for (service), which beats the global default. Exactly one global default
    must exist; `resolve()` raises if none does, because silently falling back
    to "no markup" would sell at a loss.
    """

    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True, db_index=True)

    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.CASCADE, related_name="pricing_rules"
    )
    country = models.ForeignKey(
        Country, null=True, blank=True, on_delete=models.CASCADE, related_name="pricing_rules"
    )

    markup_type = models.CharField(
        max_length=12, choices=MarkupType.choices, default=MarkupType.PERCENTAGE
    )
    markup_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("20.00"),
        help_text="Percent added on top of the converted provider cost.",
    )
    markup_fixed = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Flat GHS amount added.",
    )

    payment_fee_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("2.00"),
        help_text="Covers the MoMo collection fee charged by the aggregator.",
    )
    risk_buffer_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("3.00"),
        help_text="Covers refunds and provider failures.",
    )

    rounding = models.CharField(
        max_length=14, choices=Rounding.choices, default=Rounding.NEAREST_0_50
    )
    min_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("2.00"))
    max_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("500.00"))

    priority = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "pricing_rule"
        ordering = ["priority", "-created_at"]
        indexes = [models.Index(fields=["is_active", "service", "country"])]
        constraints = [
            models.CheckConstraint(
                check=models.Q(min_price__lte=models.F("max_price")),
                name="pricing_rule_min_lte_max",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def specificity(self) -> int:
        return (1 if self.service_id else 0) + (1 if self.country_id else 0)

    @property
    def is_global_default(self) -> bool:
        return self.service_id is None and self.country_id is None
