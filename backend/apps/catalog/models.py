from __future__ import annotations

from decimal import Decimal

from django.conf import settings
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
    SHOPPING = "SHOPPING", "Shopping"
    GAMING = "GAMING", "Gaming"
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
    #: The service's logo: a bundled asset ("/service-icons/tiktok.svg", served
    #: by the web app - see apps/catalog/service_icons.json), the URL of a logo
    #: staff uploaded (served by the API from `logo_data`), or the brand's logo
    #: on Brandfetch's CDN once staff matched the brand (apps/catalog/
    #: brand_logos.py). Empty means the frontend shows its generic fallback.
    #: This field is the one place the frontend learns which logo a service uses.
    icon_url = models.CharField(max_length=300, blank=True, default="")
    #: The website of the brand staff matched this service to ("venmo.com") -
    #: what its Brandfetch logo is looked up by. Empty: not matched.
    logo_domain = models.CharField(max_length=253, blank=True, default="")
    #: When staff last decided this service's logo in the logo queue (matched a
    #: brand, or found none). Set: the service has left the queue.
    logo_reviewed_at = models.DateTimeField(null=True, blank=True)
    #: An uploaded logo, when staff replaced the bundled one. Small (capped at
    #: upload), raw bytes rather than base64, validated before it is stored.
    logo_data = models.BinaryField(null=True, blank=True, editable=False)
    logo_content_type = models.CharField(max_length=40, blank=True, default="")
    logo_updated_at = models.DateTimeField(null=True, blank=True)
    # Short brand colour used by the frontend avatar when no logo is available.
    accent_color = models.CharField(max_length=7, blank=True, default="")
    description = models.CharField(max_length=200, blank=True, default="")
    #: Other words a customer might type for this service - "gmail" for Google,
    #: "x" for Twitter. Comma-separated; searched alongside the name and slug.
    aliases = models.CharField(max_length=200, blank=True, default="")

    #: Chosen by staff. Popular services lead the marketplace; see
    #: apps/catalog/marketplace.popular_services for how activity adds to them.
    is_popular = models.BooleanField(default=False, db_index=True)
    popular_rank = models.PositiveIntegerField(default=100)

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

    # Whether this provider has agreed, in writing, to our reselling its
    # numbers to our customers. Nothing is sold through a provider without it:
    # its offerings are never listed to customers and never charged for, even
    # when the provider is enabled and its catalogue is synced. Staff record
    # the evidence (an email, a ticket) when granting it; see admin > Providers.
    resale_authorized = models.BooleanField(default=False)
    authorization_reference = models.CharField(max_length=300, blank=True, default="")
    authorized_at = models.DateTimeField(null=True, blank=True)
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

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
    #: Where `cost_amount` came from. NOT_SYNCED (or a zero cost) means we do
    #: not know what the number costs us, and it is never sold.
    cost_source = models.CharField(
        max_length=12,
        choices=[("PROVIDER_API", "Provider API"), ("MANUAL", "Entered by staff"),
                 ("NOT_SYNCED", "Not synced")],
        default="NOT_SYNCED",
    )

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

    #: The customer price last recorded in price history. Prices are always
    #: computed live by the pricing engine; this is only what the next change
    #: is compared against, so every change can be written down.
    customer_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_updated_at = models.DateTimeField(null=True, blank=True)
    #: What the pricing engine would charge now. Equal to `customer_price`
    #: unless prices are published by review (PricingPolicy.auto_publish_prices
    #: off) and something moved - then `price_review_pending` is set until staff
    #: publish it.
    recommended_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_review_pending = models.BooleanField(default=False, db_index=True)

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


class PinnedService(BaseModel):
    """A service a customer has pinned to the top of their marketplace.

    Stored server-side so the same pins follow the customer to every device.
    One row per (user, service), enforced by the database.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pinned_services"
    )
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="pins")

    class Meta:
        db_table = "catalog_pinned_service"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "service"], name="pinned_service_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} pinned {self.service_id}"
