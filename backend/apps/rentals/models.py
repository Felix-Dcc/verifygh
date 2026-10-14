"""Number rentals: a number kept for days, not minutes.

A verification (apps/orders) is one number for one code, gone in twenty
minutes. A rental is a number the customer keeps for a fixed period - one day
to three months - and every SMS it receives in that time lands in their inbox
here. Bought from TextVerified as a *non-renewable* rental: prepaid from the
wallet, never renewed automatically, extendable on request.

Money moves through the same ledger as orders, keyed on the rental's id (or an
extension's), so refunds and spending limits match them up the same way.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Provider, Service
from apps.common.models import BaseModel

#: The provider's service name for a number that takes any app's messages.
ALL_SERVICES = "allservices"


class RentalStatus(models.TextChoices):
    #: Paid for; the provider has not confirmed the number yet.
    PENDING = "PENDING", "Setting up"
    ACTIVE = "ACTIVE", "Active"
    #: The period ran out. The number no longer receives messages.
    EXPIRED = "EXPIRED", "Ended"
    #: Cancelled while the provider still allowed it; the price came back.
    REFUNDED = "REFUNDED", "Cancelled and refunded"
    #: The provider could not supply a number; the price came back.
    FAILED = "FAILED", "Didn't go through"


#: Rentals that hold one of the customer's slots.
OPEN_RENTAL_STATUSES = frozenset({RentalStatus.PENDING, RentalStatus.ACTIVE})
#: Rentals the customer received - what they paid for was delivered.
DELIVERED_RENTAL_STATUSES = frozenset({RentalStatus.ACTIVE, RentalStatus.EXPIRED})


class Rental(BaseModel):
    """One rented number. The price fields are a snapshot taken at purchase."""

    reference = models.CharField(max_length=20, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rentals"
    )
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="rentals")
    #: The app the number is for. Null for an "all apps" number.
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.PROTECT, related_name="rentals"
    )
    #: The name the provider knows the service by ("whatsapp", "allservices").
    provider_service_name = models.CharField(max_length=64)
    days = models.PositiveIntegerField()

    # -- frozen price snapshot -------------------------------------------
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")
    #: What the provider charged (its sale total), or quoted until it says.
    provider_cost = models.DecimalField(max_digits=12, decimal_places=4,
                                        default=Decimal("0.0000"))
    provider_currency = models.CharField(max_length=3, default="USD")
    exchange_rate = models.DecimalField(max_digits=16, decimal_places=6,
                                        default=Decimal("0.000000"))
    price_breakdown = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=10, choices=RentalStatus.choices,
                              default=RentalStatus.PENDING, db_index=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")

    # -- the provider's side ---------------------------------------------
    provider_rental_id = models.CharField(max_length=128, blank=True, default="",
                                          db_index=True)
    provider_sale_id = models.CharField(max_length=128, blank=True, default="")
    phone_number = models.CharField(max_length=32, blank=True, default="")
    activated_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    #: The provider's own word, at our last look, on whether it can be refunded.
    can_refund = models.BooleanField(default=False)
    refundable_until = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # -- money -----------------------------------------------------------
    promo_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       default=Decimal("0.00"))
    cash_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                      default=Decimal("0.00"))
    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                          default=Decimal("0.00"))
    refunded_at = models.DateTimeField(null=True, blank=True)

    # -- housekeeping ----------------------------------------------------
    idempotency_key = models.CharField(max_length=128)
    #: Purchase attempts at the provider, for retries after an unclear answer.
    attempts = models.PositiveIntegerField(default=0)
    messages_checked_at = models.DateTimeField(null=True, blank=True)
    expiry_notified_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rentals_rental"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "idempotency_key"],
                                    name="rental_idempotency_unique"),
            # One upstream rental belongs to one of ours: two pointing at the
            # same one would show one customer's messages to another.
            models.UniqueConstraint(
                fields=["provider", "provider_rental_id"],
                condition=~models.Q(provider_rental_id=""),
                name="rental_provider_rental_id_unique",
            ),
            models.CheckConstraint(check=models.Q(price__gte=Decimal("0.00")),
                                   name="rental_price_non_negative"),
            models.CheckConstraint(
                check=models.Q(promo_amount__gte=Decimal("0.00"))
                & models.Q(cash_amount__gte=Decimal("0.00"))
                & models.Q(refunded_amount__gte=Decimal("0.00")),
                name="rental_amounts_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(status__in=["PENDING", "ACTIVE", "EXPIRED", "REFUNDED",
                                           "FAILED"]),
                name="rental_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "ends_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.provider_service_name} [{self.status}]"

    @property
    def is_all_services(self) -> bool:
        return self.service_id is None

    @property
    def service_label(self) -> str:
        return self.service.name if self.service_id else "Any app"

    @property
    def may_display_messages(self) -> bool:
        """Messages are shown only where the provider agreement allows it."""
        return bool(settings.VERIFYGH["DISPLAY_VERIFICATION_CODES"]
                    and self.provider.permits_code_display)


class ExtensionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed and refunded"


class RentalExtension(BaseModel):
    """More days on an active rental, bought separately. Not refundable once made."""

    rental = models.ForeignKey(Rental, on_delete=models.PROTECT, related_name="extensions")
    days = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    provider_cost = models.DecimalField(max_digits=12, decimal_places=4,
                                        default=Decimal("0.0000"))
    exchange_rate = models.DecimalField(max_digits=16, decimal_places=6,
                                        default=Decimal("0.000000"))
    promo_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       default=Decimal("0.00"))
    cash_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                      default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=ExtensionStatus.choices,
                              default=ExtensionStatus.PENDING)
    provider_extension_id = models.CharField(max_length=128, blank=True, default="")
    previous_ends_at = models.DateTimeField(null=True, blank=True)
    new_ends_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)

    class Meta:
        db_table = "rentals_extension"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["rental", "idempotency_key"],
                                    name="rental_extension_idempotency_unique"),
            models.CheckConstraint(check=models.Q(price__gte=Decimal("0.00")),
                                   name="rental_extension_price_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.rental_id} +{self.days}d [{self.status}]"


class RentalMessage(BaseModel):
    """One SMS received on a rented number. Its text is never logged."""

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name="messages")
    provider_message_id = models.CharField(max_length=128)
    sender = models.CharField(max_length=64, blank=True, default="")
    body = models.TextField(blank=True, default="")
    code = models.CharField(max_length=32, blank=True, default="")
    received_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "rentals_message"
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["rental", "provider_message_id"],
                                    name="rental_message_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.rental_id} message {self.provider_message_id}"
