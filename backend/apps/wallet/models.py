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

    #: Cash the user paid in. Withdrawable and refundable as cash.
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    #: Promotional credit (referral bonuses). Spendable on eligible purchases,
    #: never withdrawable, transferable or convertible to cash. It is a second
    #: bucket of the same wallet, not a second wallet: every movement is still
    #: an entry in the one ledger, written by the one service.
    promo_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    # Set by an admin when a wallet is under investigation. Blocks spending
    # without touching the user's ability to sign in and see their history.
    is_frozen = models.BooleanField(default=False)
    frozen_reason = models.CharField(max_length=255, blank=True, default="")

    total_deposited = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total_spent = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    #: Lifetime promotional credit granted. Never decreases, so the cost of the
    #: referral programme stays auditable even after the credit is spent.
    promo_granted = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        db_table = "wallet_wallet"
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=Decimal("0.00")), name="wallet_balance_non_negative"
            ),
            models.CheckConstraint(
                check=models.Q(promo_balance__gte=Decimal("0.00")),
                name="wallet_promo_balance_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(total_deposited__gte=Decimal("0.00"))
                & models.Q(total_spent__gte=Decimal("0.00"))
                & models.Q(promo_granted__gte=Decimal("0.00")),
                name="wallet_totals_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet<{self.user_id}> {self.currency} {self.balance}"

    @property
    def ledger_balance(self) -> Decimal:
        """Cash balance recomputed from the ledger. Used by the integrity checker."""
        return self.ledger_balance_for(FundType.CASH)

    @property
    def promo_ledger_balance(self) -> Decimal:
        return self.ledger_balance_for(FundType.PROMO)

    def ledger_balance_for(self, funds: str) -> Decimal:
        aggregate = self.ledger_entries.filter(funds=funds).aggregate(
            credits=models.Sum(
                "amount", filter=models.Q(direction=LedgerDirection.CREDIT)
            ),
            debits=models.Sum("amount", filter=models.Q(direction=LedgerDirection.DEBIT)),
        )
        credits = aggregate["credits"] or Decimal("0.00")
        debits = aggregate["debits"] or Decimal("0.00")
        return credits - debits

    @property
    def spendable(self) -> Decimal:
        """What the user can pay with: promotional credit plus cash."""
        return self.promo_balance + self.balance


class FundType(models.TextChoices):
    """Which bucket of the wallet an entry moves.

    CASH is money the user paid in: withdrawable, refundable as cash.
    PROMO is promotional credit we granted: spendable on eligible purchases
    only, and never convertible back to cash. Keeping them in one ledger (one
    sequence, one set of constraints) means promotional money gets exactly the
    same guarantees as real money, while staying countable apart from it.
    """

    CASH = "CASH", "Cash"
    PROMO = "PROMO", "Promotional credit"


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
    REFERRAL_BONUS = "REFERRAL_BONUS", "Referral bonus"


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
    LedgerEntryType.REFERRAL_BONUS: (LedgerDirection.CREDIT,),
}

#: Entry types that may only ever move one bucket. Promotional credit is
#: granted as REFERRAL_BONUS and can never leave as cash, so WITHDRAWAL is
#: pinned to CASH - there is no code path that turns promo into money.
ENTRY_TYPE_FUNDS: dict[str, tuple[str, ...]] = {
    LedgerEntryType.DEPOSIT: (FundType.CASH,),
    LedgerEntryType.WITHDRAWAL: (FundType.CASH,),
    LedgerEntryType.REFERRAL_BONUS: (FundType.PROMO,),
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
    #: Which bucket this entry moved. Existing rows are all CASH.
    funds = models.CharField(
        max_length=5, choices=FundType.choices, default=FundType.CASH, db_index=True
    )
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
                    models.Q(entry_type__in=["DEPOSIT", "REFUND", "REFERRAL_BONUS"],
                             direction="CREDIT")
                    | models.Q(entry_type__in=["PURCHASE", "WITHDRAWAL"], direction="DEBIT")
                    | models.Q(entry_type__in=["ADJUSTMENT", "REVERSAL"],
                               direction__in=["CREDIT", "DEBIT"])
                ),
                name="ledger_direction_matches_type",
            ),
            models.CheckConstraint(
                check=models.Q(sequence__gte=1), name="ledger_sequence_positive"
            ),
            # Promotional credit can only be granted as a REFERRAL_BONUS, and
            # cash can never leave the system as one. A withdrawal - the only
            # way money exits to a person - is cash-only by construction.
            models.CheckConstraint(
                check=(
                    models.Q(funds="CASH", entry_type__in=[
                        "DEPOSIT", "PURCHASE", "REFUND", "ADJUSTMENT", "WITHDRAWAL", "REVERSAL",
                    ])
                    | models.Q(funds="PROMO", entry_type__in=[
                        "REFERRAL_BONUS", "PURCHASE", "REFUND", "ADJUSTMENT", "REVERSAL",
                    ])
                ),
                name="ledger_funds_allow_entry_type",
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
