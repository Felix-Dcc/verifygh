from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Country, Provider, ProviderService, Service
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
    #: Never below the calculated price: a cost increase too small to move
    #: "nearest" rounding still reaches the customer price.
    CEIL_0_50 = "CEIL_0_50", "Round up to 0.50"
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
    #: Scope a rule to one supplier - the same service can cost different
    #: amounts from different providers.
    provider = models.ForeignKey(
        Provider, null=True, blank=True, on_delete=models.CASCADE, related_name="pricing_rules"
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

    #: By default the engine never prices below cost (see engine.cost_floor).
    #: A promotion that deliberately sells at a loss must say so here.
    allow_below_cost = models.BooleanField(default=False)

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
        return ((1 if self.service_id else 0) + (1 if self.country_id else 0)
                + (1 if self.provider_id else 0))

    @property
    def is_global_default(self) -> bool:
        return self.service_id is None and self.country_id is None and self.provider_id is None


class PriceChangeSource(models.TextChoices):
    PRICING_RULE = "PRICING_RULE", "Pricing rule changed"
    PROVIDER_COST = "PROVIDER_COST", "Provider cost changed"
    EXCHANGE_RATE = "EXCHANGE_RATE", "Pricing FX rate changed"
    OVERRIDE = "OVERRIDE", "Manual price override"
    PUBLISHED = "PUBLISHED", "Reviewed and published"
    POLICY = "POLICY", "Pricing policy changed"
    INITIAL = "INITIAL", "First recorded price"


class PriceChange(BaseModel):
    """One change to one offering's customer price. Append-only.

    Written whenever a recomputation lands on a different price than the one
    last recorded, whatever caused it - a staff edit to a rule (with who and
    why), a provider cost change from a sync, or a new exchange rate. Orders
    already carry their own frozen price; this is the audit trail for the
    price list itself.
    """

    offering = models.ForeignKey(
        ProviderService, null=True, on_delete=models.SET_NULL, related_name="price_changes"
    )
    service_name = models.CharField(max_length=80)
    country_code = models.CharField(max_length=2)
    provider_key = models.CharField(max_length=32)

    old_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")
    provider_cost = models.DecimalField(max_digits=12, decimal_places=4)
    provider_currency = models.CharField(max_length=3, default="USD")
    exchange_rate = models.DecimalField(max_digits=16, decimal_places=6)
    pricing_rule_name = models.CharField(max_length=80, blank=True, default="")

    source = models.CharField(max_length=16, choices=PriceChangeSource.choices, db_index=True)
    #: The price the rules produced, when it differs from what was charged
    #: (an override, or a published price awaiting review).
    calculated_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="price_changes",
    )
    reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "pricing_price_change"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["offering", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Price history is append-only.")
        super().save(*args, **kwargs)


class FXMode(models.TextChoices):
    MANUAL = "MANUAL", "Manual pricing rate"
    AUTOMATIC = "AUTOMATIC", "Market rate plus adjustment"


class PricingFXRate(TimeStampedModel):
    """The VerifyGH Pricing FX Rate for one currency: what a provider cost in
    that currency is converted to cedis at, for pricing.

    Deliberately separate from the market rate (ExchangeRate rows). The market
    rate is a reference; the pricing rate is a business decision that can sit
    above it to cover Mobile Money collection, conversion and settlement costs
    and FX movement between buying credit and selling numbers. It is never
    shown to customers, and never called "the exchange rate" to them.

    MANUAL: staff set the rate. It does not go stale - it is a decision, not a
    quote. AUTOMATIC: the latest market rate times (1 + adjustment%), and it
    stops pricing if the market rate is more than MAX_RATE_AGE_HOURS old.
    """

    base_currency = models.CharField(max_length=3, unique=True)
    quote_currency = models.CharField(max_length=3, default="GHS")
    mode = models.CharField(max_length=10, choices=FXMode.choices, default=FXMode.MANUAL)
    manual_rate = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    adjustment_percent = models.DecimalField(max_digits=6, decimal_places=2,
                                             default=Decimal("0.00"))
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "pricing_fx_rate"
        constraints = [
            models.CheckConstraint(
                check=models.Q(manual_rate__isnull=True) | models.Q(manual_rate__gt=0),
                name="pricing_fx_manual_positive",
            ),
            models.CheckConstraint(
                check=models.Q(adjustment_percent__gt=Decimal("-50"))
                & models.Q(adjustment_percent__lt=Decimal("100")),
                name="pricing_fx_adjustment_sane",
            ),
        ]

    def __str__(self) -> str:
        return f"Pricing FX {self.base_currency}/{self.quote_currency} [{self.mode}]"


class PricingPolicy(TimeStampedModel):
    """Business-wide pricing settings. One row (pk=1); see PricingPolicy.get()."""

    #: Warn when a price earns less than this share of what the customer pays.
    minimum_margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("10.00")
    )
    #: Refuse to save prices below the minimum margin instead of only warning.
    enforce_minimum_margin = models.BooleanField(default=False)
    #: On: provider cost, FX and rule changes reach customers straight away.
    #: Off: they become recommendations that staff review and publish.
    auto_publish_prices = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "pricing_policy"

    @classmethod
    def get(cls) -> PricingPolicy:
        policy, _ = cls.objects.get_or_create(pk=1)
        return policy


class PriceOverride(BaseModel):
    """A price staff set by hand for one offering, replacing the calculated one.

    Never silent: the calculated price is kept alongside it everywhere, the
    reason and author are required, and replacing or removing an override
    closes the old row rather than editing it.
    """

    offering = models.ForeignKey(
        ProviderService, on_delete=models.CASCADE, related_name="price_overrides"
    )
    price = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=500)
    #: Selling below provider cost, deliberately. Needs PRICING_LOSS_OVERRIDE.
    allow_loss = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "pricing_price_override"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["offering"], condition=models.Q(is_active=True),
                name="one_active_override_per_offering",
            ),
            models.CheckConstraint(check=models.Q(price__gt=0), name="override_price_positive"),
        ]


class CostSource(models.TextChoices):
    PROVIDER_API = "PROVIDER_API", "Provider API"
    MANUAL = "MANUAL", "Entered by staff"


class ProviderCostChange(BaseModel):
    """One change to what a provider charges us for one offering. Append-only."""

    offering = models.ForeignKey(
        ProviderService, null=True, on_delete=models.SET_NULL, related_name="cost_changes"
    )
    provider_key = models.CharField(max_length=32)
    service_name = models.CharField(max_length=80)
    country_code = models.CharField(max_length=2)
    old_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    new_cost = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=3)
    source = models.CharField(max_length=12, choices=CostSource.choices)
    #: How it was learned: a catalogue sync (the provider's price list) or a
    #: staff entry.
    sync_method = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "pricing_provider_cost_change"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["offering", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Provider cost history is append-only.")
        super().save(*args, **kwargs)
