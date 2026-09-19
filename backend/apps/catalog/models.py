from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class ServiceCategory(models.TextChoices):
    SOCIAL = "SOCIAL", "Social"
    MESSAGING = "MESSAGING", "Messaging"
    EMAIL = "EMAIL", "Email"
    DEVELOPER = "DEVELOPER", "Developer"
    BUSINESS = "BUSINESS", "Business"
    FINANCE = "FINANCE", "Finance"
    OTHER = "OTHER", "Other"


class Country(BaseModel):
    """A country a number can be sourced from.

    `is_enabled` is ours; `is_supported_by_provider` mirrors upstream. Both must
    be true for a country to appear in the marketplace.
    """

    code = models.CharField(max_length=2, unique=True, help_text="ISO 3166-1 alpha-2")
    name = models.CharField(max_length=80)
    dial_code = models.CharField(max_length=8, blank=True, default="")
    flag_emoji = models.CharField(max_length=8, blank=True, default="")

    is_enabled = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "catalog_country"
        ordering = ["display_order", "name"]
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Service(BaseModel):
    """A third-party service a user may need a verification number for.

    Note the framing throughout the product: we sell access to *supported*
    verification services, and the user remains responsible for complying with
    the terms of whatever service they verify against.
    """

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=80)
    category = models.CharField(
        max_length=16, choices=ServiceCategory.choices, default=ServiceCategory.OTHER,
        db_index=True,
    )
    icon_url = models.URLField(blank=True, default="")
    # Short brand colour used by the frontend avatar when no logo is available.
    accent_color = models.CharField(max_length=7, blank=True, default="")
    description = models.CharField(max_length=200, blank=True, default="")

    is_enabled = models.BooleanField(default=True, db_index=True)
    is_maintenance = models.BooleanField(default=False)
    maintenance_note = models.CharField(max_length=200, blank=True, default="")

    supports_sms = models.BooleanField(default=True)
    supports_voice = models.BooleanField(default=False)

    display_order = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "catalog_service"
        ordering = ["display_order", "name"]
        indexes = [models.Index(fields=["category", "is_enabled"])]

    def __str__(self) -> str:
        return self.name

    @property
    def is_available(self) -> bool:
        return self.is_enabled and not self.is_maintenance


class Provider(BaseModel):
    """An upstream verification provider.

    `adapter_key` selects the concrete class from the provider registry, which
    is how a provider can be swapped without touching application code.
    """

    adapter_key = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    is_enabled = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveIntegerField(
        default=100, help_text="Lower wins when several providers offer the same service."
    )

    # Contractual switch: some agreements do not permit relaying the message
    # body or code to the end user. When false, we show delivery status only.
    permits_code_display = models.BooleanField(default=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "catalog_provider"
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.name


class ProviderService(BaseModel):
    """What one provider offers for one (service, country) pair.

    `cost_amount` is the provider's price in `cost_currency` (normally USD) and
    is synced from the provider API - never typed in by hand in production.
    """

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="offerings")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="offerings")
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="offerings")

    provider_service_code = models.CharField(
        max_length=64, help_text="The provider's own identifier for this service."
    )

    cost_amount = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    cost_currency = models.CharField(max_length=3, default="USD")

    is_enabled = models.BooleanField(default=True, db_index=True)
    is_available = models.BooleanField(
        default=True, db_index=True, help_text="Upstream stock availability."
    )
    available_count = models.IntegerField(
        null=True, blank=True, help_text="Numbers in stock, when the provider reports it."
    )

    supports_sms = models.BooleanField(default=True)
    supports_voice = models.BooleanField(default=False)

    # Rough minutes a number stays reserved upstream. Drives the order TTL.
    ttl_minutes = models.PositiveIntegerField(default=20)

    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "catalog_provider_service"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "service", "country"], name="provider_service_country_unique"
            )
        ]
        indexes = [
            models.Index(fields=["service", "country", "is_enabled", "is_available"]),
            models.Index(fields=["provider", "is_enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider.name}:{self.service.slug}@{self.country.code}"

    @property
    def is_purchasable(self) -> bool:
        return (
            self.is_enabled
            and self.is_available
            and self.provider.is_enabled
            and self.service.is_available
            and self.country.is_enabled
        )

    def mark_synced(self) -> None:
        self.last_synced_at = timezone.now()
        self.save(update_fields=["last_synced_at", "updated_at"])
