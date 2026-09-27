"""Deposit orchestration and webhook processing.

The rule this module exists to enforce: **only the provider can mark a payment
successful.** Nothing the browser sends moves a payment forward. A deposit
becomes money in a wallet through exactly one path - a signature-verified
webhook, or our own outbound `fetch_charge` during reconciliation.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.audit.models import SuspicionLevel, SuspiciousActivity
from apps.audit.services import flag, record_audit
from apps.common.errors import (
    LimitExceeded,
    ProviderError,
    ServiceUnavailable,
    ValidationFailed,
)
from apps.common.ids import payment_reference
from apps.common.logging import mask_phone, redact_mapping
from apps.common.money import quantize
from apps.payments.base import ChargeStatus
from apps.payments.models import (
    TERMINAL_PAYMENT_STATUSES,
    Payment,
    PaymentStatus,
    PaymentWebhookEvent,
)
from apps.payments.registry import get_payment_provider
from apps.wallet.services import credit_deposit, get_or_create_wallet

logger = logging.getLogger("verifygh.payments")

_CHARGE_TO_PAYMENT = {
    ChargeStatus.PENDING: PaymentStatus.PENDING,
    ChargeStatus.PROCESSING: PaymentStatus.PROCESSING,
    ChargeStatus.SUCCESS: PaymentStatus.SUCCESS,
    ChargeStatus.FAILED: PaymentStatus.FAILED,
    ChargeStatus.CANCELLED: PaymentStatus.CANCELLED,
    ChargeStatus.EXPIRED: PaymentStatus.EXPIRED,
}

#: Stored for verified callbacks we could not parse. Kept visible as
#: unprocessed, but never auto-replayed - parsing it again would fail again.
UNPARSED_EVENT_TYPE = "unparsed"

# Headers worth keeping for a dispute. Everything else is dropped, so we never
# warehouse a provider's auth headers.
_KEPT_HEADERS = {
    "content-type", "user-agent", "x-forwarded-for", "x-request-id",
    "x-paystack-signature", "x-mock-signature",
}


# ---------------------------------------------------------------------------
# Initiating a deposit
# ---------------------------------------------------------------------------


def deposits_blocked_reason() -> str:
    """Why top-ups are closed right now, or "" when they are open.

    Money in is only safe when money can also be spent. A wallet the user cannot
    buy with and cannot withdraw from is, from their side, money we took and
    kept - so the catalogue being empty has to close the till, not just empty
    the shelves.
    """
    from django.conf import settings as django_settings

    if not django_settings.VERIFYGH["REQUIRE_CATALOG_FOR_DEPOSIT"]:
        return ""

    from apps.catalog.services import marketplace_readiness

    readiness = marketplace_readiness()
    if readiness["ready"]:
        return ""

    # One message whatever the cause. Which of the three preconditions failed is
    # an operational detail: a customer can do nothing with "no exchange rate",
    # and it advertises how the platform is wired.
    logger.warning("deposits_blocked", extra={k: v for k, v in readiness.items()})
    return (
        "Top-ups are paused while we restock verification numbers. "
        "Your existing balance is safe and is not affected."
    )


def initiate_deposit(*, user, amount, phone: str, network: str, request=None) -> Payment:
    amount = quantize(amount)
    wallet = get_or_create_wallet(user)

    # Checked first, before the amount is even validated: there is no useful
    # deposit into a marketplace with nothing in it, so the amount is moot.
    blocked = deposits_blocked_reason()
    if blocked:
        raise ServiceUnavailable(blocked, code="DEPOSITS_PAUSED")

    minimum = quantize(settings.VERIFYGH["MIN_DEPOSIT"])
    maximum = quantize(settings.VERIFYGH["MAX_DEPOSIT"])
    balance_cap = quantize(settings.VERIFYGH["MAX_WALLET_BALANCE"])

    if amount < minimum:
        raise ValidationFailed(f"The minimum deposit is GHS {minimum}.")
    if amount > maximum:
        raise ValidationFailed(f"The maximum single deposit is GHS {maximum}.")
    if wallet.balance + amount > balance_cap:
        raise LimitExceeded(
            f"That would take your balance above the GHS {balance_cap} limit.",
            code="WALLET_CAP_EXCEEDED",
        )

    _check_pending_deposits(user)

    reference = payment_reference()
    ttl_minutes = settings.VERIFYGH["PAYMENT_TTL_MINUTES"]

    provider = get_payment_provider()

    payment = Payment.objects.create(
        user=user,
        reference=reference,
        provider=provider.key,
        amount=amount,
        currency="GHS",
        phone=phone,
        network=network,
        status=PaymentStatus.PENDING,
        expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        ip_address=getattr(request, "client_ip", None) or None,
        metadata={"user_agent": (request.META.get("HTTP_USER_AGENT", "")[:200]
                                 if request else "")},
    )

    try:
        charge = provider.initiate_charge(
            amount=amount,
            currency="GHS",
            phone=phone,
            network=network,
            reference=reference,
            email=user.email,
            metadata={"user_id": str(user.id), "reference": reference},
        )
    except ProviderError:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = "We could not start the payment. Please try again."
        payment.completed_at = timezone.now()
        payment.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])
        logger.warning("deposit_initiation_failed", extra={"reference": reference})
        raise

    payment.provider_reference = charge.provider_reference
    payment.instructions = charge.instructions[:255]
    payment.status = _CHARGE_TO_PAYMENT.get(charge.status, PaymentStatus.PROCESSING)
    payment.save(
        update_fields=["provider_reference", "instructions", "status", "updated_at"]
    )

    record_audit(
        actor=user, action="DEPOSIT_INITIATED", target=payment, request=request,
        metadata={
            "reference": reference,
            "amount": str(amount),
            "network": network,
            "phone": mask_phone(phone),
        },
    )
    logger.info(
        "deposit_initiated",
        extra={"reference": reference, "amount": str(amount), "provider": provider.key},
    )
    return payment


def _check_pending_deposits(user) -> None:
    """Stop a user stacking up prompts they never approve."""
    pending = Payment.objects.filter(
        user=user,
        status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING],
        created_at__gte=timezone.now() - timedelta(minutes=15),
    ).count()
    if pending >= 3:
        flag(
            user=user,
            kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY,
            level=SuspicionLevel.LOW,
            description=f"{pending} deposits left pending in 15 minutes.",
        )
        raise LimitExceeded(
            "You have unfinished payments. Complete or cancel them before starting another.",
            code="TOO_MANY_PENDING_DEPOSITS",
        )


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class WebhookResult:
    def __init__(self, status: str, detail: str = "", payment: Payment | None = None):
        self.status = status
        self.detail = detail
        self.payment = payment

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail}


def process_webhook(*, provider_key: str, raw_body: bytes, headers: dict,
                    remote_ip: str | None = None) -> WebhookResult:
    """Verify, record and act on one provider callback.

    Returns a result rather than raising, because a webhook endpoint should
    answer 200 for anything it has safely recorded - providers retry on
    non-2xx, and retrying a *duplicate* is pointless noise.
    """
    provider = get_payment_provider(provider_key)

    if not provider.verify_webhook(raw_body, headers):
        logger.error("webhook_signature_invalid", extra={"provider": provider_key})
        _record_event(
            provider_key=provider_key,
            event_id=f"unverified:{hashlib.sha256(raw_body).hexdigest()[:32]}",
            event_type="unverified",
            reference="",
            signature_valid=False,
            payload={},
            headers=headers,
            raw_body=raw_body,
            remote_ip=remote_ip,
        )
        return WebhookResult("invalid_signature", "Signature verification failed.")

    try:
        event = provider.parse_webhook(raw_body, headers)
    except ProviderError as exc:
        # Genuinely from the provider (the signature checked out) but not in a
        # shape we understand - usually a new event type or an API change. It
        # must not vanish: store it where the admin health check counts it, so a
        # human sees a payment callback we could not read.
        logger.error("webhook_unparseable", extra={"provider": provider_key})
        record, _ = _record_event(
            provider_key=provider_key,
            event_id=f"unparsed:{hashlib.sha256(raw_body).hexdigest()[:32]}",
            event_type=UNPARSED_EVENT_TYPE,
            reference="",
            signature_valid=True,
            payload={"raw": raw_body.decode("utf-8", errors="replace")[:20000]},
            headers=headers,
            raw_body=raw_body,
            remote_ip=remote_ip,
        )
        if record is not None:
            record.mark_processed(error=f"unparseable: {exc}")
        return WebhookResult("unparseable", str(exc))

    record, created = _record_event(
        provider_key=provider_key,
        event_id=event.event_id,
        event_type=event.event_type,
        reference=event.reference,
        signature_valid=True,
        payload=event.raw,
        headers=headers,
        raw_body=raw_body,
        remote_ip=remote_ip,
    )

    if not created:
        # Seen before - but "seen" is not "applied". If a previous attempt
        # recorded the event and then failed to apply it, answering "duplicate"
        # here would mean the provider's retry is swallowed and the customer is
        # never credited. Re-applying is safe: the ledger's unique idempotency
        # key makes a successful replay a no-op.
        if record is not None and record.signature_valid and not record.processed:
            logger.warning(
                "webhook_reprocessing_after_failure",
                extra={"provider": provider_key, "event_id": event.event_id},
            )
        else:
            logger.info(
                "webhook_duplicate_ignored",
                extra={"provider": provider_key, "event_id": event.event_id},
            )
            return WebhookResult("duplicate", "Already processed.")

    if record is None:
        # Could neither create nor find the event row. Refuse rather than act on
        # a callback we have not managed to record.
        logger.error("webhook_record_missing", extra={"event_id": event.event_id})
        return WebhookResult("unrecorded", "Could not record the event.")

    try:
        payment = _apply_event(event, provider_key)
    except Exception as exc:
        record.mark_processed(error=repr(exc))
        logger.exception("webhook_processing_failed", extra={"event_id": event.event_id})
        # Re-raised so the endpoint answers 5xx and the provider retries. The
        # retry is what the reprocessing branch above exists to serve.
        raise

    if payment is not None:
        PaymentWebhookEvent.objects.filter(pk=record.pk).update(payment=payment)
    record.mark_processed()
    return WebhookResult("processed", "", payment)


def _record_event(*, provider_key: str, event_id: str, event_type: str, reference: str,
                  signature_valid: bool, payload: dict, headers: dict, raw_body: bytes,
                  remote_ip: str | None):
    kept = {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in _KEPT_HEADERS
    }
    # A signature is not a secret we need to keep in plain text.
    for key in list(kept):
        if "signature" in key:
            kept[key] = "[PRESENT]"

    try:
        # Savepoint: a duplicate event is expected, and its IntegrityError must
        # not poison the surrounding transaction.
        with transaction.atomic():
            record = PaymentWebhookEvent.objects.create(
                provider=provider_key,
                event_id=event_id[:128] or "unknown",
                event_type=event_type[:64],
                reference=reference[:64],
                signature_valid=signature_valid,
                payload=redact_mapping(payload or {}),
                headers=kept,
                body_sha256=hashlib.sha256(raw_body).hexdigest(),
                remote_ip=remote_ip or None,
            )
        return record, True
    except IntegrityError:
        existing = PaymentWebhookEvent.objects.filter(
            provider=provider_key, event_id=event_id[:128]
        ).first()
        return existing, False


def _apply_event(event, provider_key: str) -> Payment | None:
    payment = Payment.objects.filter(reference=event.reference).first()
    if payment is None:
        logger.error(
            "webhook_unknown_reference",
            extra={"provider": provider_key, "reference": event.reference},
        )
        return None

    if payment.provider != provider_key:
        # A valid signature from provider A says nothing about a payment made
        # with provider B. Without this check, a callback signed by any enabled
        # adapter could settle any payment whose reference it could learn.
        logger.error(
            "webhook_provider_mismatch",
            extra={
                "reference": payment.reference,
                "payment_provider": payment.provider,
                "webhook_provider": provider_key,
            },
        )
        flag(
            user=payment.user,
            kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY,
            level=SuspicionLevel.HIGH,
            description="A webhook from a different provider tried to settle this payment.",
            evidence={
                "reference": payment.reference,
                "payment_provider": payment.provider,
                "webhook_provider": provider_key,
            },
            dedupe_hours=0,
        )
        return None

    if "dispute" in (event.event_type or ""):
        # A chargeback after we credited the wallet. Never auto-reversed - the
        # money may already be spent - but a human must see it.
        flag(
            user=payment.user,
            kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY,
            level=SuspicionLevel.HIGH,
            description="The payment provider reported a dispute on this deposit.",
            evidence={"reference": payment.reference, "event": event.event_type},
            dedupe_hours=0,
        )
        return payment

    target_status = _CHARGE_TO_PAYMENT.get(event.status)
    if target_status is None or target_status not in TERMINAL_PAYMENT_STATUSES:
        # PENDING / PROCESSING, or an event type that does not move money:
        # recorded above, nothing to apply.
        return payment

    if target_status == PaymentStatus.SUCCESS:
        return _credit_payment(payment, event)

    return _mark_unsuccessful(payment, target_status, event.failure_reason)


#: How far above the requested amount a callback may go before we stop
#: crediting automatically. A genuine over-payment is rare; a provider bug that
#: scales amounts (subunits mistaken for units, say) is not, and auto-crediting
#: it would hand out money we never received.
OVERPAYMENT_TOLERANCE = Decimal("1.05")


def _credit_payment(payment: Payment, event) -> Payment:
    """Move money into the wallet, exactly once, atomically."""
    expected = quantize(payment.amount)
    credited_amount = quantize(event.amount) if event.amount is not None else expected

    if (event.currency or payment.currency).upper() != payment.currency.upper():
        # An amount in another currency is a different number entirely. Never
        # convert or credit it automatically.
        logger.error(
            "payment_currency_mismatch",
            extra={"reference": payment.reference, "expected": payment.currency,
                   "received": event.currency},
        )
        flag(
            user=payment.user,
            kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY,
            level=SuspicionLevel.HIGH,
            description="Webhook currency did not match the deposit currency.",
            evidence={"reference": payment.reference, "expected": payment.currency,
                      "received": event.currency},
            dedupe_hours=0,
        )
        Payment.objects.filter(pk=payment.pk, credited_at__isnull=True).update(
            status=PaymentStatus.PROCESSING,
            failure_reason="Currency received does not match; held for review.",
        )
        payment.refresh_from_db()
        return payment

    if event.amount is not None and credited_amount != expected:
        mismatch = {
            "reference": payment.reference,
            "expected": str(expected),
            "received": str(credited_amount),
        }
        logger.error("payment_amount_mismatch", extra=mismatch)
        flag(
            user=payment.user,
            kind=SuspiciousActivity.Kind.DEPOSIT_ANOMALY,
            level=SuspicionLevel.HIGH,
            description="Webhook amount did not match the requested deposit amount.",
            evidence=mismatch,
            dedupe_hours=0,
        )

        if credited_amount > expected * OVERPAYMENT_TOLERANCE:
            # Under-payment credits what arrived - the user gets what they paid.
            # A large over-payment does not: crediting it would create a
            # liability out of what is far more likely to be a provider or
            # integration bug. Hold it for a human instead.
            logger.error("payment_overpayment_held", extra=mismatch)
            Payment.objects.filter(pk=payment.pk, credited_at__isnull=True).update(
                status=PaymentStatus.PROCESSING,
                failure_reason=(
                    "Amount received exceeds the requested amount; held for review."
                )[:255],
            )
            payment.refresh_from_db()
            return payment

    with transaction.atomic():
        locked = _lock_payment(payment.pk)

        if locked.credited_at is not None:
            logger.info("payment_already_credited", extra={"reference": locked.reference})
            return locked

        wallet = get_or_create_wallet(locked.user)

        entry = credit_deposit(
            wallet=wallet,
            amount=credited_amount,
            # The payment reference is the idempotency key. Even if this row's
            # credited_at guard were somehow bypassed, the ledger's unique index
            # would still refuse a second credit.
            idempotency_key=f"deposit:{locked.reference}",
            payment_reference=locked.reference,
            provider=locked.provider,
            payment_id=locked.pk,
        )

        Payment.objects.filter(pk=locked.pk).update(
            status=PaymentStatus.SUCCESS,
            credited_at=timezone.now(),
            ledger_entry_id=entry.id,
            completed_at=timezone.now(),
            provider_reference=event.provider_reference or locked.provider_reference,
            failure_reason="",
        )

    payment.refresh_from_db()

    def _notify():
        from apps.notifications.services import notify

        notify(
            payment.user,
            event="PAYMENT_SUCCESSFUL",
            title="Payment received",
            body=f"Your wallet has been credited with GHS {credited_amount}.",
            channels=("EMAIL", "IN_APP"),
            context={"amount": str(credited_amount), "reference": payment.reference},
            metadata={"payment_reference": payment.reference},
        )

    transaction.on_commit(_notify)

    record_audit(
        actor=payment.user, action="DEPOSIT_CREDITED", target=payment,
        metadata={"reference": payment.reference, "amount": str(credited_amount)},
    )
    logger.info(
        "deposit_credited",
        extra={"reference": payment.reference, "amount": str(credited_amount)},
    )
    return payment


def _lock_payment(payment_id) -> Payment:
    queryset = Payment.objects.filter(pk=payment_id)
    if connection.features.has_select_for_update:
        queryset = queryset.select_for_update()
    return queryset.get()


def _mark_unsuccessful(payment: Payment, status: str, reason: str) -> Payment:
    if payment.status in TERMINAL_PAYMENT_STATUSES:
        # Never walk a settled payment backwards on a late callback.
        logger.info(
            "payment_terminal_status_kept",
            extra={"reference": payment.reference, "status": payment.status},
        )
        return payment

    Payment.objects.filter(pk=payment.pk).exclude(
        status__in=list(TERMINAL_PAYMENT_STATUSES)
    ).update(
        status=status,
        failure_reason=(reason or "")[:255],
        completed_at=timezone.now(),
    )
    payment.refresh_from_db()

    if status == PaymentStatus.FAILED:
        from apps.notifications.services import notify

        notify(
            payment.user,
            event="PAYMENT_FAILED",
            title="Payment did not go through",
            body="Your Mobile Money payment was not completed. No money has left your account.",
            channels=("EMAIL", "IN_APP"),
            context={"reference": payment.reference, "amount": str(payment.amount)},
        )

    logger.info(
        "payment_marked", extra={"reference": payment.reference, "status": status}
    )
    return payment


# ---------------------------------------------------------------------------
# Reconciliation - the safety net for lost webhooks
# ---------------------------------------------------------------------------


def reconcile_payment(payment: Payment) -> Payment:
    """Ask the provider what really happened, and apply it.

    Webhooks get lost. Without this, a user whose callback vanished would have
    paid and received nothing.
    """
    provider = get_payment_provider(payment.provider)
    try:
        charge = provider.fetch_charge(payment.reference)
    except Exception:
        logger.warning("payment_reconcile_failed", extra={"reference": payment.reference})
        return payment

    if charge.status == ChargeStatus.SUCCESS:
        from apps.payments.base import WebhookEventDTO

        synthetic = WebhookEventDTO(
            event_id=f"reconcile:{payment.reference}",
            event_type="reconciliation",
            reference=payment.reference,
            status=ChargeStatus.SUCCESS,
            provider_reference=charge.provider_reference,
            amount=charge.amount if charge.amount is not None else Decimal(payment.amount),
            currency=charge.currency,
        )
        return _credit_payment(payment, synthetic)

    target = _CHARGE_TO_PAYMENT.get(charge.status)
    if target and target in TERMINAL_PAYMENT_STATUSES:
        return _mark_unsuccessful(payment, target, charge.failure_reason)
    return payment


def replay_failed_webhook(record: PaymentWebhookEvent) -> bool:
    """Re-apply a verified event that was recorded but never applied.

    Providers give up retrying after a handful of attempts, so waiting for one
    is not a recovery plan. This lets a scheduled sweep - or an operator -
    finish the job from the raw payload we stored.
    """
    if record.processed or not record.signature_valid:
        return False

    provider = get_payment_provider(record.provider)
    try:
        event = provider.parse_webhook_payload(record.payload)
    except (AttributeError, NotImplementedError):
        # Adapter cannot rebuild an event from a stored payload.
        logger.error(
            "webhook_replay_unsupported",
            extra={"provider": record.provider, "event_id": record.event_id},
        )
        return False
    except Exception:
        logger.exception("webhook_replay_parse_failed", extra={"event_id": record.event_id})
        return False

    try:
        payment = _apply_event(event, record.provider)
    except Exception as exc:
        record.mark_processed(error=repr(exc))
        logger.exception("webhook_replay_failed", extra={"event_id": record.event_id})
        return False

    if payment is not None:
        PaymentWebhookEvent.objects.filter(pk=record.pk).update(payment=payment)
    record.mark_processed()
    logger.info("webhook_replayed", extra={"event_id": record.event_id})
    return True
