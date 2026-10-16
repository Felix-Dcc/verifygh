"""Manual Mobile Money top-ups, for when no payment gateway can collect.

8 Oct 2026: Paystack disabled the business and Moolre's API answered UP02
(merchant setup incomplete). Customers still need to top up, so:

1. The customer asks to top up an amount and gets a reference code.
2. They send that amount to the business wallet (an AirtelTigo Money number,
   reachable from any network through ExpressPay's *246#), with the code as
   the reference where the menu allows one.
3. They submit the number they paid from, the transaction ID from their
   confirmation message, and a screenshot of it. The request goes to review.
4. Staff open the business wallet, find the transfer, and approve by typing
   the amount that actually arrived and the transaction ID shown on the
   receiving wallet. Only then is the wallet credited - through the same
   once-only path as a gateway deposit (services._credit_payment).

A screenshot is evidence for staff, never proof: they are easy to edit, so
nothing is credited from one. What stops a double credit is the receiving
wallet's transaction ID, unique across every manual top-up (a database
constraint), plus the ledger's own idempotency key.

Switched on and off by staff (MaintenanceState.manual_deposits). The review
queue keeps working while it is off, so open claims can still be settled.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.constants import AdminPermission, MomoNetwork
from apps.common.errors import (
    Conflict,
    InvalidStateTransition,
    LimitExceeded,
    NotFound,
    ProviderError,
    ServiceUnavailable,
    ValidationFailed,
)
from apps.common.ids import payment_reference
from apps.common.money import format_ghs, quantize
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO
from apps.payments.models import Payment, PaymentEvidence, PaymentStatus

logger = logging.getLogger("verifygh.payments.manual")

KEY = "manual"

#: How long a top-up request waits for its claim before it lapses.
REQUEST_TTL = timedelta(hours=24)

REJECT_REASONS = (
    "We could not find this payment on our wallet.",
    "The amount we received is different from the amount claimed.",
    "The reference or transaction ID does not match.",
    "This payment was already used for another top-up.",
)

_TXN_ID = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{3,39}$")


class ManualDepositProvider(PaymentProvider):
    """The registry entry for manual top-ups.

    Registered so every sweep and status check that looks up a payment's
    provider gets an answer. It never starts a charge and never settles one:
    a person does, in approve().
    """

    key = KEY
    display_name = "Manual Mobile Money transfer"
    #: Never a PAYMENT_PROVIDER: production refuses to boot with it selected.
    is_implemented = False
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)

    def initiate_charge(self, **kwargs) -> ChargeDTO:
        raise ProviderError("Manual top-ups are started from the manual top-up form.")

    def fetch_charge(self, reference: str) -> ChargeDTO:
        # Raised, so reconcile_payment changes nothing: staff decide.
        raise ProviderError("Manual top-ups are checked by hand.")

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        return False

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        raise ProviderError("Manual top-ups have no callbacks.")


def _cfg(name: str):
    return settings.VERIFYGH[name]


def is_enabled() -> bool:
    from apps.common.models import MaintenanceState

    state = MaintenanceState.objects.filter(pk=1).first()
    return bool(state and state.manual_deposits)


def details() -> dict:
    """What the deposit page needs to show the manual option."""
    number = str(_cfg("MANUAL_DEPOSIT_NUMBER") or "")
    enabled = is_enabled() and bool(number)
    return {
        "enabled": enabled,
        "number": number if enabled else "",
        "network": str(_cfg("MANUAL_DEPOSIT_NETWORK") or ""),
        "account_name": str(_cfg("MANUAL_DEPOSIT_ACCOUNT_NAME") or ""),
        "ussd": str(_cfg("MANUAL_DEPOSIT_USSD") or ""),
        "min": str(quantize(_cfg("MIN_DEPOSIT"))),
        "max": str(quantize(_cfg("MANUAL_DEPOSIT_MAX"))),
    }


def _open_claims(user):
    return Payment.objects.filter(
        user=user, provider=KEY, status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING])


# -- customer ------------------------------------------------------------------


def start(*, user, amount, request=None) -> Payment:
    """A top-up request: the amount, and the reference to send it with."""
    from apps.common import maintenance
    from apps.wallet.services import get_or_create_wallet

    if not is_enabled() or not _cfg("MANUAL_DEPOSIT_NUMBER"):
        raise ServiceUnavailable("Manual top-ups are not available right now.",
                                 code="MANUAL_DEPOSITS_OFF")
    if maintenance.current()["mode"] == "ALL_PAUSED":
        raise ServiceUnavailable(maintenance.current()["message"], code="DEPOSITS_PAUSED")
    if settings.VERIFYGH["REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE"] and not user.is_email_verified:
        raise ValidationFailed("Confirm your email address before topping up.",
                               code="EMAIL_NOT_VERIFIED")

    amount = quantize(amount)
    minimum, maximum = quantize(_cfg("MIN_DEPOSIT")), quantize(_cfg("MANUAL_DEPOSIT_MAX"))
    if not minimum <= amount <= maximum:
        raise ValidationFailed(
            f"Manual top-ups are between {format_ghs(minimum)} and {format_ghs(maximum)}.")
    from apps.wallet.services import lock_wallet

    wallet = get_or_create_wallet(user)
    _check_manual_limits(user, wallet, amount)
    with transaction.atomic():
        # Again under the wallet lock, so requests sent together cannot all
        # slip past the open-request and daily limits (A-12).
        _check_manual_limits(user, lock_wallet(wallet), amount)
        payment = Payment.objects.create(
            user=user, reference=payment_reference(), provider=KEY, amount=amount,
            currency="GHS", phone="", network=MomoNetwork.AT, status=PaymentStatus.PENDING,
            expires_at=timezone.now() + REQUEST_TTL,
            ip_address=getattr(request, "client_ip", None) or None,
            metadata={"manual": True, "claimed_amount": str(amount)},
        )
    logger.info("manual_deposit_started", extra={"reference": payment.reference,
                                                 "amount": str(amount)})
    return payment


def _check_manual_limits(user, wallet, amount) -> None:
    if wallet.balance + amount > quantize(_cfg("MAX_WALLET_BALANCE")):
        raise LimitExceeded("That would take your balance above the wallet limit.",
                            code="WALLET_CAP_EXCEEDED")
    if _open_claims(user).count() >= int(_cfg("MANUAL_DEPOSIT_MAX_OPEN")):
        raise LimitExceeded("You already have top-ups waiting. Finish or wait for those first.",
                            code="TOO_MANY_OPEN_TOPUPS")
    today = Payment.objects.filter(
        user=user, provider=KEY, created_at__gte=timezone.now() - timedelta(days=1),
    ).exclude(status__in=[PaymentStatus.FAILED, PaymentStatus.EXPIRED,
                          PaymentStatus.CANCELLED]).aggregate(total=Sum("amount"))["total"]
    if (today or Decimal("0")) + amount > quantize(_cfg("MANUAL_DEPOSIT_DAILY_LIMIT")):
        raise LimitExceeded(
            f"Manual top-ups are limited to {format_ghs(_cfg('MANUAL_DEPOSIT_DAILY_LIMIT'))} "
            "a day.", code="DAILY_TOPUP_LIMIT")


def _evidence(files) -> list[tuple[bytes, str]]:
    from apps.numbers.services import read_evidence

    return read_evidence(files, required=True)


def claim(*, user, reference: str, sender_phone: str, network: str, transaction_id: str,
          files) -> Payment:
    """The customer says they have paid. Goes to staff; credits nothing."""
    from apps.accounts.phone import normalise_gh
    from apps.notifications.staff import alert_staff

    txn = re.sub(r"\s+", "", str(transaction_id or "")).upper()
    if not _TXN_ID.match(txn):
        raise ValidationFailed("Enter the transaction ID exactly as it appears in your "
                               "confirmation message.", code="INVALID_TRANSACTION_ID")
    if network not in MomoNetwork.values:
        raise ValidationFailed("Choose the network you paid from.")
    try:
        phone = normalise_gh(sender_phone)
    except Exception:
        raise ValidationFailed("Enter the mobile number you paid from.") from None
    images = _evidence(files)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if payment is None or payment.user_id != user.id or payment.provider != KEY:
            raise NotFound("We could not find that top-up.")
        if payment.status != PaymentStatus.PENDING:
            raise InvalidStateTransition("This top-up has already been submitted.")
        if payment.expires_at and payment.expires_at <= timezone.now():
            raise InvalidStateTransition("This top-up request has expired. Start a new one.",
                                         code="PAYMENT_EXPIRED")
        reused = Payment.objects.filter(provider=KEY, metadata__sender_transaction_id=txn) \
            .exclude(pk=payment.pk).exclude(status__in=[PaymentStatus.FAILED,
                                                        PaymentStatus.EXPIRED]).exists()
        hashes = [hashlib.sha256(data).hexdigest() for data, _ in images]
        reused_image = PaymentEvidence.objects.filter(sha256__in=hashes) \
            .exclude(payment=payment).exists()
        if reused or reused_image:
            raise Conflict("This payment has already been used for another top-up.",
                           code="TOPUP_ALREADY_CLAIMED")

        for (data, content_type), digest in zip(images, hashes, strict=True):
            PaymentEvidence.objects.create(payment=payment, data=data, content_type=content_type,
                                           size=len(data), sha256=digest)
        payment.phone = phone
        payment.network = network
        payment.status = PaymentStatus.PROCESSING
        # Waiting on staff, not on the customer: the expiry sweep leaves it.
        payment.expires_at = None
        payment.metadata = {**(payment.metadata or {}), "sender_transaction_id": txn,
                            "claimed_at": timezone.now().isoformat()}
        payment.save(update_fields=["phone", "network", "status", "expires_at", "metadata",
                                    "updated_at"])
        alert_staff(
            permission=AdminPermission.WALLET_ADJUST, event="STAFF_MANUAL_DEPOSIT",
            title=f"Top-up to check: {format_ghs(payment.amount)}",
            body=(f"{payment.reference}: {format_ghs(payment.amount)} sent from "
                  f"{phone[-4:].rjust(len(phone), '*')}. Check the wallet, then approve or "
                  "reject in Admin > Manual top-ups."),
            link="/admin/manual-deposits", reference=payment.reference,
        )
    logger.info("manual_deposit_claimed", extra={"reference": payment.reference})
    return payment


# -- staff ---------------------------------------------------------------------


def approve(*, reference: str, amount_received, receipt_id: str, actor, request=None) -> Payment:
    """Credit a top-up whose money staff have seen arrive on the wallet."""
    from apps.audit.services import record_admin_action
    from apps.payments.services import _credit_payment

    receipt = re.sub(r"\s+", "", str(receipt_id or "")).upper()
    if not _TXN_ID.match(receipt):
        raise ValidationFailed("Enter the transaction ID shown on the receiving wallet.")
    amount = quantize(amount_received)
    if not Decimal("0") < amount <= quantize(_cfg("MAX_DEPOSIT")):
        raise ValidationFailed("Enter the amount that arrived on the wallet.")

    try:
        with transaction.atomic():
            payment = Payment.objects.select_for_update().filter(reference=reference,
                                                                 provider=KEY).first()
            if payment is None:
                raise NotFound("We could not find that top-up.")
            if payment.status != PaymentStatus.PROCESSING or payment.credited_at:
                raise InvalidStateTransition("This top-up has already been decided.")
            if Payment.objects.filter(provider=KEY, provider_reference=receipt) \
                    .exclude(pk=payment.pk).exists():
                raise Conflict("That transaction was already used to credit another top-up.",
                               code="RECEIPT_ALREADY_USED")
            claimed = payment.amount
            record_admin_action(
                admin=actor, action="MANUAL_DEPOSIT_APPROVE", target=payment,
                reason=f"Seen on wallet: {format_ghs(amount)}, transaction {receipt}",
                before={"status": payment.status, "claimed": str(claimed)},
                after={"credited": str(amount), "receipt": receipt}, request=request,
            )
            # The wallet gets what arrived, whatever was claimed.
            payment.amount = amount
            payment.metadata = {**(payment.metadata or {}), "approved_by": str(actor.pk),
                                "received_amount": str(amount)}
            payment.save(update_fields=["amount", "metadata", "updated_at"])
            payment = _credit_payment(payment, WebhookEventDTO(
                event_id=f"manual:{payment.reference}", event_type="manual.approved",
                reference=payment.reference, status=ChargeStatus.SUCCESS,
                provider_reference=receipt, amount=amount, currency="GHS"))
    except IntegrityError:
        raise Conflict("That transaction was already used to credit another top-up.",
                       code="RECEIPT_ALREADY_USED") from None
    logger.info("manual_deposit_approved", extra={"reference": reference, "amount": str(amount)})
    return payment


def reject(*, reference: str, reason: str, actor, request=None) -> Payment:
    from apps.audit.services import record_admin_action
    from apps.notifications.services import notify

    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Say why - pick one of the reasons.")
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference,
                                                             provider=KEY).first()
        if payment is None:
            raise NotFound("We could not find that top-up.")
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
            raise InvalidStateTransition("This top-up has already been decided.")
        record_admin_action(admin=actor, action="MANUAL_DEPOSIT_REJECT", target=payment,
                            reason=reason[:500], before={"status": payment.status},
                            after={"status": PaymentStatus.FAILED}, request=request)
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = reason[:255]
        payment.completed_at = timezone.now()
        payment.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])
    notify(payment.user, event="PAYMENT_FAILED", title="Top-up not confirmed",
           body=(f"We could not confirm your top-up {payment.reference}: {reason} "
                 "If money left your account, contact support with the transaction ID."),
           channels=("IN_APP", "EMAIL"), metadata={"payment_reference": payment.reference})
    return payment


def set_enabled(*, enabled: bool, reason: str, actor, request=None) -> dict:
    from apps.audit.services import record_admin_action
    from apps.common.models import MaintenanceState

    if not isinstance(enabled, bool):
        raise ValidationFailed("Say whether manual top-ups should be on.")
    if len(str(reason or "").strip()) < 3:
        raise ValidationFailed("Say why.")
    if enabled and not _cfg("MANUAL_DEPOSIT_NUMBER"):
        raise ValidationFailed("Set MANUAL_DEPOSIT_NUMBER before switching manual top-ups on.")
    with transaction.atomic():
        MaintenanceState.objects.get_or_create(pk=1)
        state = MaintenanceState.objects.select_for_update().get(pk=1)
        before = state.manual_deposits
        state.manual_deposits = enabled
        state.updated_by = actor
        state.save(update_fields=["manual_deposits", "updated_by", "updated_at"])
        record_admin_action(admin=actor, action="MANUAL_DEPOSITS_ON" if enabled
                            else "MANUAL_DEPOSITS_OFF", target=state, reason=str(reason)[:500],
                            before={"manual_deposits": before},
                            after={"manual_deposits": enabled}, request=request)
    return details()
