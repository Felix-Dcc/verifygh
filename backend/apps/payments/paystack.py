"""Paystack Mobile Money adapter (Ghana).

Paystack is the default production aggregator because it supports GHS mobile
money collections directly. The endpoints below are the ones documented in
Paystack's public API reference:

    POST /charge                     - start a mobile money charge
    GET  /transaction/verify/{ref}   - authoritative status lookup
    webhook signature: HMAC-SHA512 of the raw body, header x-paystack-signature

TODO(credentials): before go-live, re-check three things against the current
Paystack docs for your account, because they are the ones that vary by market
and can change:
  1. the `mobile_money.provider` codes for MTN / Telecel / AirtelTigo,
  2. whether your account uses the charge flow directly or a hosted
     transaction-initialise flow,
  3. the exact set of webhook `event` values you should act on.
Everything else in this file is provider-agnostic plumbing.

You must also register the webhook URL in the Paystack dashboard:
    https://<your-api-domain>/api/v1/payments/webhooks/paystack/
and restrict it to Paystack's published IP range at the edge.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError, ServiceUnavailable
from apps.common.idempotency import derive
from apps.common.logging import mask_phone
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.paystack")

REQUEST_TIMEOUT = 25
SIGNATURE_HEADER = "x-paystack-signature"

# TODO(credentials): confirm these against your account's current documentation.
NETWORK_CODES = {
    MomoNetwork.MTN: "mtn",
    MomoNetwork.TELECEL: "vod",
    MomoNetwork.AT: "atl",
}

#: Paystack's `data.status`, mapped to what the customer must actually do.
#:
#: The two that matter for Ghana mobile money are `pay_offline` and `send_otp`,
#: and they are opposites. `pay_offline` means wait - the handset is being
#: prompted. `send_otp` means act - Paystack has texted a code and will sit
#: there until we POST it back.
#:
#: Both used to map to PROCESSING, so both rendered the same "approve on your
#: phone, waiting for confirmation" screen. A customer in the send_otp branch
#: received a code, had nowhere to enter it, and watched the charge expire.
#: That is the bug this table fixes.
STATUS_MAP = {
    "success": ChargeStatus.SUCCESS,
    "failed": ChargeStatus.FAILED,
    "abandoned": ChargeStatus.CANCELLED,
    "reversed": ChargeStatus.FAILED,
    "timeout": ChargeStatus.EXPIRED,
    "pending": ChargeStatus.PENDING,
    "ongoing": ChargeStatus.PROCESSING,
    "processing": ChargeStatus.PROCESSING,
    "queued": ChargeStatus.PROCESSING,
    # Documented for Ghana MoMo: "the customer is also prompted to authorise
    # the transaction on their phones... within 180 seconds".
    "pay_offline": ChargeStatus.PHONE_AUTH_REQUIRED,
    # Documented on the Charge API: completed with POST /charge/submit_otp.
    "send_otp": ChargeStatus.OTP_REQUIRED,
}

#: Card-only authorisation steps. They should never appear on a mobile_money
#: charge, and we cannot complete any of them, so they are treated as failures
#: rather than left to time out in front of the customer.
UNSUPPORTED_ACTIONS = {"send_pin", "send_phone", "send_birthday", "send_address", "open_url"}

#: Paystack's documented ceiling for a Ghana mobile money authorisation. After
#: this the network fails the transaction, whatever our own expiry says.
MOBILE_MONEY_WINDOW_SECONDS = 180


def _fallback_email() -> str:
    """The address used only if a charge somehow has no customer email."""
    sender = str(settings.DEFAULT_FROM_EMAIL or "")
    if "<" in sender and ">" in sender:
        sender = sender.split("<", 1)[1].split(">", 1)[0]
    return sender.strip() or "payments@verifygh.com"


def to_subunit(amount: Decimal) -> int:
    """GHS 12.34 -> 1234 pesewas. Paystack works in the smallest unit."""
    return int((Decimal(amount) * 100).to_integral_value())


def from_subunit(value) -> Decimal:
    return (Decimal(str(value)) / 100).quantize(Decimal("0.01"))


class PaystackProvider(PaymentProvider):
    key = "paystack"
    display_name = "Paystack Mobile Money"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PAYMENT_CREDENTIALS.get("paystack", {})
        self.secret_key = credentials.get("secret_key", "")
        self.base_url = str(credentials.get("base_url", "https://api.paystack.co")).rstrip("/")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.secret_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.is_configured:
            raise ServiceUnavailable(
                "Mobile Money payments are not available right now.",
                code="PAYMENT_PROVIDER_NOT_CONFIGURED",
            )
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                method, url, headers=self._headers(), timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.Timeout as exc:
            # A timeout is NOT a failure: the charge may well have been created.
            # Reconciliation via fetch_charge decides, never this code path.
            logger.warning("paystack_timeout", extra={"path": path})
            raise ProviderError("The payment provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("paystack_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the payment provider.") from exc

        if response.status_code == 429:
            raise ServiceUnavailable(
                "The payment provider is busy. Please try again shortly.",
                code="PAYMENT_PROVIDER_RATE_LIMITED",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("paystack_unreadable_response", extra={"status": response.status_code})
            raise ProviderError("The payment provider returned an unreadable response.") from exc

        if response.status_code >= 400 or not payload.get("status", False):
            # Log the provider's message for support, show the user nothing of it.
            logger.error(
                "paystack_error",
                extra={
                    "status": response.status_code,
                    "provider_message": str(payload.get("message", ""))[:200],
                },
            )
            raise ProviderError("The payment could not be started. Please try again.")

        return payload

    # -- charges ---------------------------------------------------------

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        provider_code = NETWORK_CODES.get(network)
        if provider_code is None:
            raise ProviderError("That mobile money network is not supported yet.")

        body = {
            # Paystack validates this and rejects reserved domains such as
            # .example, so the fallback comes from configuration rather than a
            # placeholder. In practice every account has an email: registration
            # requires one, and initiate_deposit passes the customer's.
            "email": email or _fallback_email(),
            "amount": to_subunit(amount),
            "currency": currency,
            "reference": reference,
            "mobile_money": {"phone": phone, "provider": provider_code},
            "metadata": metadata or {},
        }

        logger.info(
            "paystack_charge_initiating",
            extra={"reference": reference, "network": network, "phone": mask_phone(phone)},
        )
        payload = self._request("POST", "/charge", json=body)
        data = payload.get("data", {})
        raw_status = str(data.get("status", "pending")).lower()
        return self._charge_from(data, raw_status, reference,
                                 amount=amount, currency=currency)

    def _charge_from(self, data: dict, raw_status: str, reference: str, *,
                     amount: Decimal | None = None, currency: str = "GHS") -> ChargeDTO:
        """One place that turns a Paystack `data` block into a ChargeDTO."""
        if raw_status in UNSUPPORTED_ACTIONS:
            # Nothing we can do drives these forward, so say so now rather than
            # showing a spinner until the window closes.
            logger.error("paystack_unsupported_action",
                         extra={"reference": reference, "action": raw_status})
            return ChargeDTO(
                provider_reference=str(data.get("reference") or reference),
                status=ChargeStatus.FAILED,
                amount=amount,
                currency=currency,
                failure_reason="This payment needs a step we cannot complete. "
                               "Please try again.",
                raw={"status": raw_status},
            )

        status = STATUS_MAP.get(raw_status)
        if status is None:
            # Unknown states are never success and never terminal: PENDING lets
            # verification and the expiry sweep settle it.
            logger.warning("paystack_unknown_status",
                           extra={"reference": reference, "provider_status": raw_status[:40]})
            status = ChargeStatus.PENDING

        terminal_failure = status in (
            ChargeStatus.FAILED, ChargeStatus.CANCELLED, ChargeStatus.EXPIRED
        )
        return ChargeDTO(
            provider_reference=str(data.get("reference") or reference),
            status=status,
            amount=amount,
            currency=currency,
            # Paystack's own wording for the step the customer is on. Preferred
            # over anything we invent, because it matches the SMS they just got.
            instructions=str(data.get("display_text", "") or "")[:255],
            failure_reason=(
                str(data.get("gateway_response", "") or "")[:200]
                if terminal_failure
                else ""
            ),
            raw={"status": raw_status},
        )

    def submit_otp(self, *, reference: str, otp: str) -> ChargeDTO:
        """Complete a charge that stopped at `send_otp`.

        Documented as POST /charge/submit_otp with {otp, reference}. The code
        itself is never logged - it is a bearer credential for one payment, and
        a log line is the wrong place for it.
        """
        logger.info("paystack_submitting_otp", extra={"reference": reference})
        payload = self._request(
            "POST", "/charge/submit_otp", json={"otp": otp, "reference": reference}
        )
        data = payload.get("data", {})
        raw_status = str(data.get("status", "")).lower()
        logger.info("paystack_otp_submitted",
                    extra={"reference": reference, "provider_status": raw_status[:40]})
        return self._charge_from(data, raw_status, reference,
                                 amount=from_subunit(data.get("amount", 0)) or None,
                                 currency=str(data.get("currency", "GHS")))

    def fetch_charge(self, reference: str) -> ChargeDTO:
        payload = self._request("GET", f"/transaction/verify/{reference}")
        data = payload.get("data", {})
        raw_status = str(data.get("status", "")).lower()
        return self._charge_from(
            data, raw_status, reference,
            amount=from_subunit(data.get("amount", 0)),
            currency=str(data.get("currency", "GHS")),
        )

    # -- webhooks --------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        """HMAC-SHA512 over the exact bytes received, compared in constant time."""
        if not self.secret_key:
            logger.error("paystack_webhook_no_secret")
            return False

        provided = headers.get(SIGNATURE_HEADER, "")
        if not provided:
            logger.warning("paystack_webhook_unsigned")
            return False

        expected = hmac.new(
            self.secret_key.encode("utf-8"), raw_body, hashlib.sha512
        ).hexdigest()
        ok = hmac.compare_digest(expected, str(provided))
        if not ok:
            logger.error("paystack_webhook_bad_signature")
        return ok

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("Unreadable webhook payload.") from exc

        event = str(payload.get("event", ""))
        data = payload.get("data", {})
        reference = str(data.get("reference", ""))
        raw_status = str(data.get("status", "")).lower()

        # Only these two events may move a payment. Everything else Paystack
        # sends (transfers, refunds, disputes, subscriptions) is recorded and
        # ignored: several of them carry data.status == "success", and mapping
        # that generically would let a non-charge event confirm a deposit.
        if event == "charge.success" and raw_status == "success":
            status = ChargeStatus.SUCCESS
        elif event == "charge.failed" or (event.startswith("charge.") and raw_status == "failed"):
            status = ChargeStatus.FAILED
        else:
            status = ChargeStatus.PROCESSING  # recorded, no state change

        # The id must identify the *event*, not the transaction. Paystack's
        # data.id is the transaction id, shared by every event about it - using
        # it alone made the first event for a transaction swallow every later
        # one as a "duplicate", including the success. Deterministic, never
        # random: a genuine replay must produce the same id.
        transaction_id = str(data.get("id") or "")
        if transaction_id:
            event_id = f"{event}:{transaction_id}"
        else:
            event_id = derive(
                "paystack", event, reference, raw_status, str(data.get("amount", ""))
            )

        return WebhookEventDTO(
            event_id=event_id,
            event_type=event,
            reference=reference,
            provider_reference=reference,
            status=status,
            amount=from_subunit(data.get("amount", 0)) if data.get("amount") is not None else None,
            currency=str(data.get("currency", "GHS")),
            failure_reason=str(data.get("gateway_response", ""))[:200],
            raw={"event": event, "status": raw_status},
        )

    def health_check(self) -> bool:
        return self.is_configured
