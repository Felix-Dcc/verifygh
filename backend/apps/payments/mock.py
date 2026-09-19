"""Mock MoMo provider.

Lets the whole deposit flow - prompt, webhook, signature check, idempotency,
ledger credit - be exercised without a merchant account or real cedis.

It signs its webhooks with a real HMAC using MOCK_PAYMENT_SECRET, so the
signature-verification path under test is the same code that will run in
production, not a bypass.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.mock")

CACHE_PREFIX = "mockpay:"
CACHE_TTL = 60 * 60 * 6
SIGNATURE_HEADER = "X-Mock-Signature"

#: Tests set this to force an outcome. None means "succeed".
FORCE_OUTCOME: str | None = None


def _secret() -> bytes:
    return str(settings.PAYMENT_CREDENTIALS["mock"]["secret_key"]).encode("utf-8")


def sign(raw_body: bytes) -> str:
    return hmac.new(_secret(), raw_body, hashlib.sha512).hexdigest()


class MockPaymentProvider(PaymentProvider):
    key = "mock"
    display_name = "Mock Mobile Money (development)"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        outcome = FORCE_OUTCOME or "SUCCESS"
        provider_reference = f"mockpay_{secrets.token_hex(8)}"

        if outcome == "REJECT_AT_INITIATION":
            raise ProviderError("The payment provider rejected the request.")

        cache.set(
            f"{CACHE_PREFIX}{reference}",
            {
                "provider_reference": provider_reference,
                "amount": str(amount),
                "currency": currency,
                "phone": phone,
                "network": network,
                "outcome": outcome,
            },
            CACHE_TTL,
        )

        logger.info(
            "mock_charge_initiated",
            extra={"reference": reference, "network": network, "outcome": outcome},
        )
        return ChargeDTO(
            provider_reference=provider_reference,
            status=ChargeStatus.PENDING,
            amount=amount,
            currency=currency,
            instructions=(
                "Approve the Mobile Money prompt on your phone. "
                "If you do not see it, dial your network's MoMo shortcode and approve "
                "the pending payment."
            ),
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        provided = headers.get(SIGNATURE_HEADER.lower(), "")
        if not provided:
            return False
        return hmac.compare_digest(sign(raw_body), str(provided))

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("Unreadable webhook payload.") from exc

        data = payload.get("data", {})
        status_text = str(payload.get("status", "success")).upper()
        status = {
            "SUCCESS": ChargeStatus.SUCCESS,
            "FAILED": ChargeStatus.FAILED,
            "CANCELLED": ChargeStatus.CANCELLED,
            "EXPIRED": ChargeStatus.EXPIRED,
        }.get(status_text, ChargeStatus.PROCESSING)

        return WebhookEventDTO(
            event_id=str(payload.get("event_id", "")),
            event_type=str(payload.get("event", "charge.update")),
            reference=str(data.get("reference", "")),
            provider_reference=str(data.get("provider_reference", "")),
            status=status,
            amount=Decimal(str(data["amount"])) if data.get("amount") is not None else None,
            currency=str(data.get("currency", "GHS")),
            failure_reason=str(data.get("failure_reason", "")),
            raw=payload,
        )

    def fetch_charge(self, reference: str) -> ChargeDTO:
        state = cache.get(f"{CACHE_PREFIX}{reference}")
        if state is None:
            raise ProviderError("Unknown charge reference.")
        outcome = state["outcome"]
        status = {
            "SUCCESS": ChargeStatus.SUCCESS,
            "FAIL": ChargeStatus.FAILED,
            "TIMEOUT": ChargeStatus.PENDING,
        }.get(outcome, ChargeStatus.SUCCESS)
        return ChargeDTO(
            provider_reference=state["provider_reference"],
            status=status,
            amount=Decimal(state["amount"]),
            currency=state["currency"],
        )


# -- test / demo helpers ----------------------------------------------------


def force_outcome(outcome: str | None) -> None:
    """Pin the next mock charges to SUCCESS / FAIL / TIMEOUT / REJECT_AT_INITIATION."""
    global FORCE_OUTCOME
    FORCE_OUTCOME = outcome


def build_webhook(*, reference: str, amount, status: str = "SUCCESS", event_id: str | None = None,
                  currency: str = "GHS", provider_reference: str = "",
                  failure_reason: str = "") -> tuple[bytes, dict]:
    """Build a correctly-signed mock webhook.

    Returns (raw_body, headers). Tests post these straight at the webhook
    endpoint, so the production verification path is what runs.
    """
    payload = {
        "event_id": event_id or f"evt_{secrets.token_hex(10)}",
        "event": "charge.update",
        "status": status,
        "data": {
            "reference": reference,
            "provider_reference": provider_reference or f"mockpay_{secrets.token_hex(6)}",
            "amount": str(amount),
            "currency": currency,
            "failure_reason": failure_reason,
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return raw_body, {SIGNATURE_HEADER: sign(raw_body)}
