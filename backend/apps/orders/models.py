from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Country, Provider, Service
from apps.common.models import BaseModel, ImmutableModel


class OrderStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    PAYMENT_PENDING = "PAYMENT_PENDING", "Payment pending"
    PROCESSING = "PROCESSING", "Processing"
    NUMBER_ASSIGNED = "NUMBER_ASSIGNED", "Number assigned"
    WAITING_FOR_CODE = "WAITING_FOR_CODE", "Waiting for code"
    CODE_RECEIVED = "CODE_RECEIVED", "Code received"
    COMPLETED = "COMPLETED", "Completed"
    EXPIRED = "EXPIRED", "Expired"
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Failed"
    REFUNDED = "REFUNDED", "Refunded"


#: The only legal moves. Anything else raises rather than silently writing -
#: a state machine that accepts every transition is just a status column.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.CREATED: {
        OrderStatus.PAYMENT_PENDING,
        OrderStatus.PROCESSING,
        OrderStatus.FAILED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PAYMENT_PENDING: {
        OrderStatus.PROCESSING,
        OrderStatus.FAILED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PROCESSING: {
        OrderStatus.NUMBER_ASSIGNED,
        OrderStatus.FAILED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.NUMBER_ASSIGNED: {
        OrderStatus.WAITING_FOR_CODE,
        OrderStatus.CODE_RECEIVED,
        OrderStatus.EXPIRED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.WAITING_FOR_CODE: {
        OrderStatus.CODE_RECEIVED,
        OrderStatus.EXPIRED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.CODE_RECEIVED: {
        OrderStatus.COMPLETED,
        OrderStatus.EXPIRED,
    },
    # Terminal-but-refundable.
    OrderStatus.EXPIRED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: {OrderStatus.REFUNDED},
    OrderStatus.FAILED: {OrderStatus.REFUNDED},
    # Fully terminal.
    OrderStatus.COMPLETED: set(),
    OrderStatus.REFUNDED: set(),
}

ACTIVE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.CREATED,
        OrderStatus.PAYMENT_PENDING,
        OrderStatus.PROCESSING,
        OrderStatus.NUMBER_ASSIGNED,
        OrderStatus.WAITING_FOR_CODE,
        OrderStatus.CODE_RECEIVED,
    }
)

TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.COMPLETED,
        OrderStatus.EXPIRED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
        OrderStatus.REFUNDED,
    }
)

#: Statuses where the user got nothing of value, so a refund is owed.
REFUNDABLE_STATUSES = frozenset(
    {OrderStatus.EXPIRED, OrderStatus.CANCELLED, OrderStatus.FAILED}
)


class RefundStatus(models.TextChoices):
    NONE = "NONE", "Not refunded"
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"


class Order(BaseModel):
    """One verification purchase.

    The price fields are a *snapshot*, written once at purchase. The pricing
    engine can change the next day and this order still explains itself: what
    the provider cost, what rate was used, what markup applied.
    """

    reference = models.CharField(max_length=20, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )

    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="orders")
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="orders")
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="orders")

    provider_order_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    provider_service_code = models.CharField(max_length=64, blank=True, default="")

    phone_number = models.CharField(max_length=32, blank=True, default="")

    # -- frozen price snapshot -------------------------------------------
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")
    provider_cost = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000")
    )
    provider_currency = models.CharField(max_length=3, default="USD")
    exchange_rate = models.DecimalField(
        max_digits=16, decimal_places=6, default=Decimal("0.000000")
    )
    price_breakdown = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.CREATED, db_index=True
    )
    failure_reason = models.CharField(max_length=255, blank=True, default="")

    # -- verification result ---------------------------------------------
    verification_code = models.CharField(max_length=32, blank=True, default="")
    verification_message = models.TextField(blank=True, default="")
    code_received_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # -- money -----------------------------------------------------------
    #: The cash half of the purchase. Kept under its original name so every
    #: order written before promotional credit existed still reads correctly.
    debit_entry_id = models.UUIDField(null=True, blank=True)
    #: The promotional half, when promotional credit paid for part of the order.
    promo_debit_entry_id = models.UUIDField(null=True, blank=True)
    #: How the price was split. Recorded at purchase so a refund can return each
    #: bucket to itself instead of converting promotional credit into cash.
    promo_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    cash_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    refund_status = models.CharField(
        max_length=10, choices=RefundStatus.choices, default=RefundStatus.NONE, db_index=True
    )

    idempotency_key = models.CharField(max_length=128, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "orders_order"
        ordering = ["-created_at"]
        constraints = [
            # The purchase endpoint is safe to retry: a repeat with the same key
            # returns the original order instead of buying a second number.
            models.UniqueConstraint(
                fields=["user", "idempotency_key"], name="order_idempotency_unique"
            ),
            # One upstream reservation belongs to one order. Two orders pointing
            # at the same provider reservation would mean one number billed
            # twice, or one customer's code shown to another.
            models.UniqueConstraint(
                fields=["provider", "provider_order_id"],
                condition=~models.Q(provider_order_id=""),
                name="order_provider_order_id_unique",
            ),
            models.CheckConstraint(
                check=models.Q(price__gte=Decimal("0.00")), name="order_price_non_negative"
            ),
            models.CheckConstraint(
                check=models.Q(promo_amount__gte=Decimal("0.00"))
                & models.Q(cash_amount__gte=Decimal("0.00")),
                name="order_split_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(status__in=[
                    "CREATED", "PAYMENT_PENDING", "PROCESSING", "NUMBER_ASSIGNED",
                    "WAITING_FOR_CODE", "CODE_RECEIVED", "COMPLETED", "EXPIRED", "CANCELLED",
                    "FAILED", "REFUNDED",
                ]),
                name="order_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["provider", "provider_order_id"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.service_id} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_ORDER_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ORDER_STATUSES

    @property
    def is_refundable(self) -> bool:
        return self.status in REFUNDABLE_STATUSES and self.refund_status == RefundStatus.NONE

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ALLOWED_TRANSITIONS.get(self.status, set())

    @property
    def may_display_code(self) -> bool:
        """Codes are shown only where the provider agreement allows it."""
        return bool(
            settings.VERIFYGH["DISPLAY_VERIFICATION_CODES"]
            and self.provider.permits_code_display
        )


class OrderEvent(ImmutableModel):
    """One line of an order's timeline.

    This table *is* the timeline the user sees on the active-order screen, and
    the thing support reads when a customer disputes an order. Append-only.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=OrderStatus.choices)
    label = models.CharField(max_length=120)
    detail = models.CharField(max_length=255, blank=True, default="")
    is_system = models.BooleanField(default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_events",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "orders_order_event"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["order", "created_at"])]

    def __str__(self) -> str:
        return f"{self.order_id}: {self.label}"


class RefundReason(models.TextChoices):
    PROVIDER_FAILED = "PROVIDER_FAILED", "Provider could not supply a number"
    NO_CODE_RECEIVED = "NO_CODE_RECEIVED", "No verification code arrived"
    USER_CANCELLED = "USER_CANCELLED", "Cancelled before use"
    ADMIN_GOODWILL = "ADMIN_GOODWILL", "Goodwill refund"
    DUPLICATE_ORDER = "DUPLICATE_ORDER", "Duplicate order"
    #: A code was delivered but staff upheld a report that the number could not
    #: be used for the service - see apps/numbers.
    NUMBER_UNUSABLE = "NUMBER_UNUSABLE", "Number unusable for the service"


class Refund(BaseModel):
    """A refund decision and its ledger consequence.

    One refund per order, enforced by a unique constraint - the cheapest way to
    make double-refunding impossible.
    """

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="refund")
    reference = models.CharField(max_length=40, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")

    reason = models.CharField(max_length=32, choices=RefundReason.choices)
    note = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(
        max_length=10, choices=RefundStatus.choices, default=RefundStatus.PENDING, db_index=True
    )
    is_automatic = models.BooleanField(default=True)

    ledger_entry_id = models.UUIDField(null=True, blank=True)
    #: How the refund was returned, mirroring how the order was paid.
    promo_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    cash_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    provider_refund_requested = models.BooleanField(default=False)
    provider_refund_accepted = models.BooleanField(default=False)

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issued_refunds",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders_refund"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=Decimal("0.00")), name="refund_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.amount}"
