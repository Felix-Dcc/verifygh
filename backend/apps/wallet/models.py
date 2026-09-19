from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, ImmutableModel


class Wallet(BaseModel):
    """A user's GHS balance.

    `balance` is a *cached projection* of the ledger, not the source of truth.
    It exists so we can read a balance without summing every entry, and the
    reconciliation job re-derives it from `WalletLedgerEntry` and alerts on drift.

    The CHECK constraint is the last line of defence: even a bug in the service
    layer cannot drive a wallet negative.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    currency = models.CharField(max_length=3, default="GHS")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    # Set by an admin when a wallet is under investigation. Blocks spending
    # without touching the user's ability to sign in and see their history.
    is_frozen = models.BooleanField(default=False)
    frozen_reason = models.CharField(max_length=255, blank=True, default="")

    total_deposited = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total_spent = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "wallet_wallet"
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=Decimal("0.00")), name="wallet_balance_non_negative"
            ),
            models.CheckConstraint(
                check=models.Q(total_deposited__gte=Decimal("0.00"))
                & models.Q(total_spent__gte=Decimal("0.00")),
                name="wallet_totals_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet<{self.user_id}> {self.currency} {self.balance}"

    @property
    def ledger_balance(self) -> Decimal:
        """Balance recomputed from the ledger. Used by the integrity checker."""
        aggregate = self.ledger_entries.aggregate(
            credits=models.Sum(
                "amount", filter=models.Q(direction=LedgerDirection.CREDIT)
            ),
            debits=models.Sum("amount", filter=models.Q(direction=LedgerDirection.DEBIT)),
        )
        credits = aggregate["credits"] or Decimal("0.00")
        debits = aggregate["debits"] or Decimal("0.00")
        return credits - debits


class LedgerDirection(models.TextChoices):
    CREDIT = "CREDIT", "Credit"
    DEBIT = "DEBIT", "Debit"


class LedgerEntryType(models.TextChoices):
    DEPOSIT = "DEPOSIT", "Deposit"
    PURCHASE = "PURCHASE", "Purchase"
    REFUND = "REFUND", "Refund"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    WITHDRAWAL = "WITHDRAWAL", "Withdrawal"
    REVERSAL = "REVERSAL", "Reversal"


# Which direction each entry type is allowed to move money. Enforced in the
# service layer so a typo cannot turn a purchase into a credit.
ENTRY_TYPE_DIRECTIONS: dict[str, tuple[str, ...]] = {
    LedgerEntryType.DEPOSIT: (LedgerDirection.CREDIT,),
    LedgerEntryType.PURCHASE: (LedgerDirection.DEBIT,),
    LedgerEntryType.REFUND: (LedgerDirection.CREDIT,),
    LedgerEntryType.WITHDRAWAL: (LedgerDirection.DEBIT,),
    # Adjustments and reversals are the only two-way types, and both are
    # admin-only and require a reason.
    LedgerEntryType.ADJUSTMENT: (LedgerDirection.CREDIT, LedgerDirection.DEBIT),
    LedgerEntryType.REVERSAL: (LedgerDirection.CREDIT, LedgerDirection.DEBIT),
}


class LedgerStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class WalletLedgerEntry(ImmutableModel):
    """One immutable movement of money.

    Every row records the balance before and after, so any historical balance can
    be reconstructed without replaying the whole table, and a tampered row is
    detectable because it breaks the chain with its neighbours.

    `idempotency_key` is unique per wallet. This is what makes a repeated payment
    webhook a no-op: the second insert violates the constraint rather than
    crediting twice.
    """

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="ledger_entries")
    reference = models.CharField(max_length=40, unique=True, db_index=True)
    idempotency_key = models.CharField(max_length=128, db_index=True)

    #: Per-wallet running sequence, assigned under the wallet lock. Timestamps
    #: are not enough: several entries can share a millisecond, and then the
    #: ledger has no defined order. A gap in this column means a row was deleted.
    sequence = models.PositiveBigIntegerField()

    entry_type = models.CharField(max_length=16, choices=LedgerEntryType.choices, db_index=True)
    direction = models.CharField(max_length=6, choices=LedgerDirection.choices)
    status = models.CharField(
        max_length=10, choices=LedgerStatus.choices, default=LedgerStatus.POSTED
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)

    # The other side of the entry: "MOMO:paystack", "PROVIDER:mock",
    # "ADMIN:<uuid>". Gives us a double-entry view without a second table.
    counterparty = models.CharField(max_length=64, blank=True, default="")

    description = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    # Weak links, so the ledger never depends on another table's lifecycle.
    related_payment_id = models.UUIDField(null=True, blank=True, db_index=True)
    related_order_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_ledger_entries",
    )

    class Meta:
        db_table = "wallet_ledger_entry"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "idempotency_key"], name="ledger_idempotency_unique"
            ),
            models.UniqueConstraint(
                fields=["wallet", "sequence"], name="ledger_sequence_unique"
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=Decimal("0.00")), name="ledger_amount_positive"
            ),
            models.CheckConstraint(
                check=models.Q(balance_after__gte=Decimal("0.00")),
                name="ledger_balance_after_non_negative",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(entry_type__in=["DEPOSIT", "REFUND"], direction="CREDIT")
                    | models.Q(entry_type__in=["PURCHASE", "WITHDRAWAL"], direction="DEBIT")
                    | models.Q(entry_type__in=["ADJUSTMENT", "REVERSAL"],
                               direction__in=["CREDIT", "DEBIT"])
                ),
                name="ledger_direction_matches_type",
            ),
            models.CheckConstraint(
                check=models.Q(sequence__gte=1), name="ledger_sequence_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["entry_type", "-created_at"]),
            models.Index(fields=["related_order_id"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.direction == LedgerDirection.CREDIT else "-"
        return f"{self.reference} {sign}{self.amount}"

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == LedgerDirection.CREDIT else -self.amount
