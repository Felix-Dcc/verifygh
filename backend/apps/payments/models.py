from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.accounts.constants import MomoNetwork
from apps.common.models import BaseModel, ImmutableModel


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    # Two states the customer has to be told apart, because one needs them to
    # type and the other needs them to wait. Showing "waiting for confirmation"
    # to somebody holding an unused SMS code is how a payment dies silently.
    OTP_REQUIRED = "OTP_REQUIRED", "Waiting for the one-time code"
    PHONE_AUTH = "PHONE_AUTH", "Waiting for approval on the handset"
    SUCCESS = "SUCCESS", "Successful"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


#: Statuses where the customer still has something to do, or we are still
#: waiting on the network. None of them has moved money.
AWAITING_PAYMENT_STATUSES = frozenset(
    {
        PaymentStatus.PENDING,
        PaymentStatus.PROCESSING,
        PaymentStatus.OTP_REQUIRED,
        PaymentStatus.PHONE_AUTH,
    }
)


TERMINAL_PAYMENT_STATUSES = frozenset(
    {
        PaymentStatus.SUCCESS,
        PaymentStatus.FAILED,
        PaymentStatus.CANCELLED,
        PaymentStatus.EXPIRED,
    }
)


class PaymentDirection(models.TextChoices):
    COLLECTION = "COLLECTION", "Collection (deposit)"
    PAYOUT = "PAYOUT", "Payout (withdrawal)"


class Payment(BaseModel):
    """A MoMo collection attempt.

    `reference` is ours and is what the provider echoes in its webhook; it is
    unique, so a provider retrying a callback always lands on the same row.

    `credited_at` is the marker that the wallet has already been credited for
    this payment. Together with the ledger's unique idempotency key, it is the
    second of two independent defences against double-crediting.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )
    reference = models.CharField(max_length=40, unique=True, db_index=True)

    direction = models.CharField(
        max_length=12, choices=PaymentDirection.choices, default=PaymentDirection.COLLECTION
    )
    provider = models.CharField(max_length=32, db_index=True)
    provider_reference = models.CharField(max_length=128, blank=True, default="", db_index=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")

    phone = models.CharField(max_length=20)
    network = models.CharField(max_length=10, choices=MomoNetwork.choices)

    status = models.CharField(
        max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    #: The provider's own wording for the step the customer is on. Preferred
    #: over anything we write, because it matches the SMS they just received.
    instructions = models.CharField(max_length=255, blank=True, default="")
    #: One-time codes submitted for this payment. Bounded so a stolen reference
    #: cannot be used to guess a six-digit code; the code itself is never stored.
    otp_attempts = models.PositiveSmallIntegerField(default=0)

    credited_at = models.DateTimeField(
        null=True, blank=True, help_text="When the wallet was credited for this payment."
    )
    ledger_entry_id = models.UUIDField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["provider", "provider_reference"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=Decimal("0.00")), name="payment_amount_positive"
            ),
            # Derived from the enum rather than repeated by hand. The hardcoded
            # copy went stale the first time a status was added, and the
            # database - correctly - refused every row using the new one.
            models.CheckConstraint(
                check=models.Q(status__in=PaymentStatus.values),
                name="payment_status_valid",
            ),
            # The credit and the SUCCESS status are written in one UPDATE; a row
            # with one and not the other means something bypassed the service.
            models.CheckConstraint(
                check=models.Q(credited_at__isnull=True) | models.Q(status="SUCCESS"),
                name="payment_credited_only_when_successful",
            ),
            # A manual top-up is settled by the transaction ID staff read on
            # the receiving wallet. One incoming transfer, one credit - ever.
            models.UniqueConstraint(
                fields=["provider_reference"],
                condition=models.Q(provider="manual") & ~models.Q(provider_reference=""),
                name="payment_manual_receipt_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.currency} {self.amount} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PAYMENT_STATUSES

    @property
    def is_credited(self) -> bool:
        return self.credited_at is not None


class PaymentWebhookEvent(ImmutableModel):
    """Every webhook we receive, stored raw before anything is acted on.

    `UNIQUE(provider, event_id)` is the primary replay defence: the second copy
    of an event fails to insert, and the handler returns 200 without touching
    the wallet. Storing the raw body also means a disputed payment can be
    reconstructed months later.

    The body is redacted of anything credential-shaped before storage.
    """

    provider = models.CharField(max_length=32, db_index=True)
    event_id = models.CharField(max_length=128, db_index=True)
    event_type = models.CharField(max_length=64, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="", db_index=True)

    signature_valid = models.BooleanField(default=False)
    processed = models.BooleanField(default=False, db_index=True)
    processing_error = models.TextField(blank=True, default="")

    payload = models.JSONField(default=dict, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    body_sha256 = models.CharField(max_length=64, blank=True, default="")
    remote_ip = models.GenericIPAddressField(null=True, blank=True)

    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="webhook_events"
    )

    class Meta:
        db_table = "payments_webhook_event"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"], name="webhook_event_unique_per_provider"
            )
        ]
        indexes = [models.Index(fields=["provider", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id}"

    # Processed is the one field allowed to change after insert, so the
    # immutability guard is relaxed for exactly that transition.
    def mark_processed(self, error: str = "") -> None:
        PaymentWebhookEvent.objects.filter(pk=self.pk).update(
            processed=not error, processing_error=error[:2000]
        )


class PaymentEvidence(BaseModel):
    """A screenshot a customer attached to a manual top-up claim.

    Supporting evidence for staff, never proof: a credit needs the money seen
    on the receiving wallet. Kept in the database (there is no persistent
    disk), served only to staff with headers that keep it an image.
    """

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="evidence")
    data = models.BinaryField(editable=False)
    content_type = models.CharField(max_length=20)
    size = models.PositiveIntegerField()
    #: The same screenshot sent for two claims is the first thing to catch.
    sha256 = models.CharField(max_length=64, db_index=True)

    class Meta:
        db_table = "payments_payment_evidence"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Evidence for {self.payment_id}"
