"""The ledger service.

This module is the **only** place in the codebase that writes `Wallet.balance`.
Nothing else may touch it - not a view, not a task, not the Django admin.

Three guarantees, each backed by the database rather than by Python:

1. **Atomicity** - the ledger row and the balance move in one transaction.
2. **Idempotency** - `UNIQUE(wallet, idempotency_key)`. A replayed webhook loses
   the race to the index and returns the original entry instead of crediting twice.
3. **No double-spend** - the wallet row is locked with `SELECT ... FOR UPDATE`
   (where the backend supports it) *and* the balance update is a compare-and-set,
   so two concurrent debits cannot both read the same starting balance and win.
   `CHECK (balance >= 0)` catches anything that still slips through.

**Two buckets, one ledger.** A wallet holds cash (`balance`) and promotional
credit (`promo_balance`). Every entry declares which one it moves, so the three
guarantees above apply to promotional credit unchanged, and the two can still be
counted separately. Promotional credit is never withdrawable: the database
refuses a WITHDRAWAL against it, and nothing converts one bucket into the other.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F

from apps.common.errors import Conflict, InsufficientFunds, ValidationFailed
from apps.common.ids import ledger_reference
from apps.common.money import ZERO, quantize
from apps.wallet.models import (
    ENTRY_TYPE_DIRECTIONS,
    ENTRY_TYPE_FUNDS,
    FundType,
    LedgerDirection,
    LedgerEntryType,
    Wallet,
    WalletLedgerEntry,
)

logger = logging.getLogger("verifygh.wallet")

MAX_CAS_ATTEMPTS = 4

#: The wallet column each bucket keeps its balance in.
BALANCE_FIELD = {FundType.CASH: "balance", FundType.PROMO: "promo_balance"}


class WalletFrozen(Conflict):
    code = "WALLET_FROZEN"
    message = "This wallet is temporarily frozen. Please contact support."


def get_or_create_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _lock(wallet_id) -> Wallet:
    """Lock the wallet row where the backend supports it.

    SQLite (dev/test) has no row locks; correctness there comes from the
    compare-and-set below plus SQLite's whole-database write lock.
    """
    queryset = Wallet.objects.filter(pk=wallet_id)
    if connection.features.has_select_for_update:
        queryset = queryset.select_for_update()
    return queryset.get()


def post_entry(
    *,
    wallet: Wallet,
    amount,
    entry_type: str,
    direction: str,
    idempotency_key: str,
    description: str = "",
    counterparty: str = "",
    metadata: dict | None = None,
    related_payment_id=None,
    related_order_id=None,
    created_by=None,
    allow_frozen: bool = False,
    funds: str = FundType.CASH,
) -> WalletLedgerEntry:
    """Post one immutable ledger entry and move the balance with it.

    `funds` selects the bucket: CASH by default, PROMO for promotional credit.
    Returns the existing entry unchanged if `idempotency_key` was already used
    for this wallet - callers can safely retry.
    """
    amount = quantize(amount)
    if amount <= ZERO:
        raise ValidationFailed("Amount must be greater than zero.")
    if not idempotency_key:
        raise ValidationFailed("An idempotency key is required for every ledger entry.")

    allowed = ENTRY_TYPE_DIRECTIONS.get(entry_type)
    if allowed is None:
        raise ValidationFailed(f"Unknown ledger entry type: {entry_type}")
    if direction not in allowed:
        raise ValidationFailed(f"{entry_type} entries cannot be a {direction}.")

    if funds not in BALANCE_FIELD:
        raise ValidationFailed(f"Unknown fund type: {funds}")
    allowed_funds = ENTRY_TYPE_FUNDS.get(entry_type)
    if allowed_funds is not None and funds not in allowed_funds:
        # e.g. a WITHDRAWAL against promotional credit: promotional credit is
        # not money and must never leave the platform.
        raise ValidationFailed(f"{entry_type} entries cannot move {funds} funds.")
    balance_field = BALANCE_FIELD[funds]

    last_error: Exception | None = None

    for attempt in range(MAX_CAS_ATTEMPTS):
        try:
            with transaction.atomic():
                locked = _lock(wallet.pk)

                existing = WalletLedgerEntry.objects.filter(
                    wallet_id=locked.pk, idempotency_key=idempotency_key
                ).first()
                if existing is not None:
                    logger.info(
                        "ledger_replay_ignored",
                        extra={"reference": existing.reference, "entry_type": entry_type},
                    )
                    return existing

                bucket_balance = getattr(locked, balance_field)

                if direction == LedgerDirection.DEBIT:
                    if locked.is_frozen and not allow_frozen:
                        raise WalletFrozen()
                    if bucket_balance < amount:
                        raise InsufficientFunds(
                            "Your balance is insufficient.",
                            details={
                                "balance": str(bucket_balance),
                                "required": str(amount),
                                "shortfall": str(quantize(amount - bucket_balance)),
                                "funds": funds,
                            },
                        )

                balance_before = bucket_balance
                delta = amount if direction == LedgerDirection.CREDIT else -amount
                balance_after = quantize(balance_before + delta)

                # Compare-and-set: the update only applies if nobody changed the
                # balance since we read it. Without row locks this is what makes
                # concurrent debits safe; with them, it simply never fails.
                updates = {balance_field: balance_after}
                if entry_type == LedgerEntryType.DEPOSIT:
                    updates["total_deposited"] = F("total_deposited") + amount
                elif entry_type == LedgerEntryType.PURCHASE:
                    updates["total_spent"] = F("total_spent") + amount
                elif entry_type == LedgerEntryType.REFUND:
                    updates["total_spent"] = F("total_spent") - amount
                elif entry_type == LedgerEntryType.REFERRAL_BONUS:
                    # Lifetime cost of the referral programme; never decreases.
                    updates["promo_granted"] = F("promo_granted") + amount

                changed = Wallet.objects.filter(
                    pk=locked.pk, **{balance_field: balance_before}
                ).update(**updates)

                if changed != 1:
                    raise _Retry()

                last_sequence = (
                    WalletLedgerEntry.objects.filter(wallet_id=locked.pk)
                    .order_by("-sequence")
                    .values_list("sequence", flat=True)
                    .first()
                    or 0
                )

                entry = WalletLedgerEntry.objects.create(
                    wallet_id=locked.pk,
                    reference=ledger_reference(),
                    sequence=last_sequence + 1,
                    idempotency_key=idempotency_key,
                    entry_type=entry_type,
                    funds=funds,
                    direction=direction,
                    amount=amount,
                    currency=locked.currency,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    counterparty=counterparty,
                    description=description[:255],
                    metadata=metadata or {},
                    related_payment_id=related_payment_id,
                    related_order_id=related_order_id,
                    created_by=created_by,
                )

            logger.info(
                "ledger_entry_posted",
                extra={
                    "reference": entry.reference,
                    "entry_type": entry_type,
                    "direction": direction,
                    "funds": funds,
                    "wallet_id": str(wallet.pk),
                },
            )
            return entry

        except _Retry as exc:
            last_error = exc
            continue
        except OperationalError as exc:
            # Transient lock contention (SQLite busy, or a lock timeout under
            # Postgres). Safe to retry: nothing was committed.
            if attempt >= MAX_CAS_ATTEMPTS - 1:
                raise
            last_error = exc
            logger.info("ledger_lock_contention_retry", extra={"attempt": attempt})
            time.sleep(0.05 * (attempt + 1))
            continue
        except IntegrityError as exc:
            # Lost the race on UNIQUE(wallet, idempotency_key): the other writer
            # already posted this exact entry. That is success, not failure.
            existing = WalletLedgerEntry.objects.filter(
                wallet_id=wallet.pk, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                return existing
            # Not a replay - two writers collided on the sequence or the
            # reference. Both are safe to retry with fresh values.
            last_error = exc
            if attempt < MAX_CAS_ATTEMPTS - 1:
                continue
            raise exc

    logger.error("ledger_cas_exhausted", extra={"wallet_id": str(wallet.pk)})
    raise Conflict(
        "We could not complete that just now. Please try again.",
        code="WALLET_CONTENTION",
    ) from last_error


class _Retry(Exception):
    """Internal: the compare-and-set lost, so re-read and try again."""


# ---------------------------------------------------------------------------
# Typed wrappers. Callers use these, not post_entry directly.
# ---------------------------------------------------------------------------


def credit_deposit(*, wallet: Wallet, amount, idempotency_key: str, payment_reference: str,
                   provider: str, payment_id=None) -> WalletLedgerEntry:
    return post_entry(
        wallet=wallet,
        amount=amount,
        entry_type=LedgerEntryType.DEPOSIT,
        direction=LedgerDirection.CREDIT,
        idempotency_key=idempotency_key,
        description=f"Mobile Money deposit {payment_reference}",
        counterparty=f"MOMO:{provider}",
        related_payment_id=payment_id,
        metadata={"payment_reference": payment_reference},
        # A deposit into a frozen wallet is allowed: we hold the money, we do
        # not bounce it back to the user's MoMo account.
        allow_frozen=True,
    )


def debit_purchase(*, wallet: Wallet, amount, idempotency_key: str, order_id, order_reference: str,
                   service_name: str, funds: str = FundType.CASH) -> WalletLedgerEntry:
    return post_entry(
        wallet=wallet,
        amount=amount,
        entry_type=LedgerEntryType.PURCHASE,
        direction=LedgerDirection.DEBIT,
        idempotency_key=idempotency_key,
        description=f"{service_name} verification ({order_reference})",
        counterparty="PLATFORM:orders",
        related_order_id=order_id,
        metadata={"order_reference": order_reference},
        funds=funds,
    )


class Charge:
    """How one purchase was paid for: promotional credit first, then cash."""

    def __init__(self, promo=ZERO, cash=ZERO, promo_entry=None, cash_entry=None):
        self.promo = quantize(promo)
        self.cash = quantize(cash)
        self.promo_entry = promo_entry
        self.cash_entry = cash_entry

    @property
    def total(self) -> Decimal:
        return quantize(self.promo + self.cash)


def split_charge(wallet: Wallet, amount) -> tuple[Decimal, Decimal]:
    """Split `amount` into (promotional, cash) at the documented priority.

    **Promotional credit is spent first.** It is the part the user cannot
    withdraw or get back as cash, so spending it first is what makes it worth
    something to them - and it means a refund returns cash as cash.
    """
    amount = quantize(amount)
    promo = min(quantize(wallet.promo_balance), amount)
    return promo, quantize(amount - promo)


def charge_order(*, wallet: Wallet, amount, order_id, order_reference: str,
                 service_name: str) -> Charge:
    """Pay for an order from the wallet: promotional credit first, then cash.

    Runs inside the caller's transaction and posts one ledger entry per bucket,
    each with its own idempotency key, so a retry of the same order repeats
    neither. Insufficiency is judged on the two buckets together, because that
    is what the user can actually spend.
    """
    amount = quantize(amount)
    wallet.refresh_from_db(fields=["balance", "promo_balance", "is_frozen"])
    if wallet.is_frozen:
        raise WalletFrozen()

    promo_part, cash_part = split_charge(wallet, amount)
    if quantize(wallet.balance) < cash_part:
        raise InsufficientFunds(
            "Your balance is insufficient.",
            details={
                "balance": str(wallet.balance),
                "promotional_balance": str(wallet.promo_balance),
                "spendable": str(wallet.spendable),
                "required": str(amount),
                "shortfall": str(quantize(amount - wallet.spendable)),
            },
        )

    charge = Charge(promo=promo_part, cash=cash_part)
    if promo_part > ZERO:
        charge.promo_entry = debit_purchase(
            wallet=wallet, amount=promo_part, idempotency_key=f"order:{order_id}:promo",
            order_id=order_id, order_reference=order_reference, service_name=service_name,
            funds=FundType.PROMO,
        )
    if cash_part > ZERO:
        # The cash key keeps its original form, so orders placed before
        # promotional credit existed stay idempotent against their old key.
        charge.cash_entry = debit_purchase(
            wallet=wallet, amount=cash_part, idempotency_key=f"order:{order_id}",
            order_id=order_id, order_reference=order_reference, service_name=service_name,
            funds=FundType.CASH,
        )
    return charge


def credit_referral_bonus(*, wallet: Wallet, amount, idempotency_key: str, referral_id,
                          reward_reference: str) -> WalletLedgerEntry:
    """Grant promotional credit for a referral. Not cash, and never becomes cash."""
    return post_entry(
        wallet=wallet,
        amount=amount,
        entry_type=LedgerEntryType.REFERRAL_BONUS,
        direction=LedgerDirection.CREDIT,
        idempotency_key=idempotency_key,
        description="Referral bonus (promotional credit)",
        counterparty="PLATFORM:referrals",
        metadata={"referral_id": str(referral_id), "reward_reference": reward_reference},
        funds=FundType.PROMO,
        # A frozen wallet can receive the credit; spending is what freezing stops.
        allow_frozen=True,
    )


def credit_refund(*, wallet: Wallet, amount, idempotency_key: str, order_id,
                  order_reference: str, reason: str,
                  funds: str = FundType.CASH) -> WalletLedgerEntry:
    return post_entry(
        wallet=wallet,
        amount=amount,
        entry_type=LedgerEntryType.REFUND,
        direction=LedgerDirection.CREDIT,
        idempotency_key=idempotency_key,
        description=f"Refund for {order_reference}",
        counterparty="PLATFORM:orders",
        related_order_id=order_id,
        metadata={"reason": reason[:200], "order_reference": order_reference},
        allow_frozen=True,
        funds=funds,
    )


def adjust(*, wallet: Wallet, amount, direction: str, idempotency_key: str, reason: str,
           admin, funds: str = FundType.CASH) -> WalletLedgerEntry:
    """Admin balance adjustment. The reason is mandatory and is audited separately."""
    if not reason or not reason.strip():
        raise ValidationFailed("A reason is required for a wallet adjustment.")
    return post_entry(
        wallet=wallet,
        amount=amount,
        entry_type=LedgerEntryType.ADJUSTMENT,
        direction=direction,
        idempotency_key=idempotency_key,
        description=f"Adjustment: {reason.strip()[:200]}",
        counterparty=f"ADMIN:{admin.pk}",
        metadata={"reason": reason.strip()[:500]},
        created_by=admin,
        allow_frozen=True,
        funds=funds,
    )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def verify_wallet_integrity(wallet: Wallet) -> dict:
    """Re-derive both balances from the ledger and report any drift.

    Also walks the entries in order to confirm every row's balance_before
    matches the previous row's balance_after *in its own bucket*. A break in
    that chain means a row was inserted or edited outside this service. The
    sequence is shared across buckets, so it is checked once, globally.
    """
    derived = quantize(wallet.ledger_balance)
    drift = quantize(wallet.balance - derived)
    promo_derived = quantize(wallet.promo_ledger_balance)
    promo_drift = quantize(wallet.promo_balance - promo_derived)

    chain_breaks = []
    running = {FundType.CASH: Decimal("0.00"), FundType.PROMO: Decimal("0.00")}
    expected_sequence = 1
    entries = list(
        wallet.ledger_entries.order_by("sequence").only(
            "reference", "sequence", "balance_before", "balance_after", "amount", "direction",
            "funds",
        )
    )
    for entry in entries:
        if entry.balance_before != running[entry.funds]:
            chain_breaks.append(
                {
                    "reference": entry.reference,
                    "sequence": entry.sequence,
                    "funds": entry.funds,
                    "expected_before": str(running[entry.funds]),
                    "recorded_before": str(entry.balance_before),
                }
            )
        if entry.sequence != expected_sequence:
            # A gap means a row was deleted; a repeat means the sequence was
            # written outside this service.
            chain_breaks.append(
                {
                    "reference": entry.reference,
                    "sequence": entry.sequence,
                    "expected_sequence": expected_sequence,
                }
            )
        expected_sequence = entry.sequence + 1
        running[entry.funds] = entry.balance_after

    return {
        "wallet_id": str(wallet.pk),
        "stored_balance": str(wallet.balance),
        "derived_balance": str(derived),
        "drift": str(drift),
        "stored_promo_balance": str(wallet.promo_balance),
        "derived_promo_balance": str(promo_derived),
        "promo_drift": str(promo_drift),
        "ok": drift == ZERO and promo_drift == ZERO and not chain_breaks,
        "chain_breaks": chain_breaks,
        "entry_count": len(entries),
    }
