"""Moolre Mobile Money adapter (Ghana).

Moolre Ltd is a Bank of Ghana-licensed Enhanced PSP. Built from its published
API reference (https://docs.moolre.com, the full text at
/llms-full-live.txt, read 8 Oct 2026) and checked against its sandbox:

    POST /open/transact/payment  - collect from a payer's phone
    POST /open/transact/status   - authoritative status, by our externalref
    callback                     - JSON POST to the URL on the wallet's API
                                   service; data.secret is the wallet's
                                   callback secret

The collection flow, as the sandbox answers it:

* The first request answers TR099 (the network's prompt was sent; the payer
  approves with their PIN) - or TP14: Moolre texted the payer a one-time code
  to verify the number, first-time payers mostly.
* For TP14, the same request is sent again, same externalref, with `otpcode`.
  TP17 means the number is verified; TP15 means the code was wrong.
* After TP17 the request is sent once more without the code, and TR099 says
  the prompt is on its way.

Callbacks are NOT signed: the only proof in one is a static secret in the
body. So a callback is never trusted on its own - it is a prompt to ask
/open/transact/status, and only that answer can settle a payment. A forged
callback, even with a leaked secret, can therefore never credit a wallet.

The payer is charged the amount plus the network's fee (about 1%: GH₵10.00
showed as GH₵10.10 in the sandbox); the wallet receives the amount.
"""

from __future__ import annotations

import hmac
import json
import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError, ServiceUnavailable
from apps.common.idempotency import derive
from apps.common.logging import mask_phone
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.moolre")

REQUEST_TIMEOUT = 25
LIVE_BASE_URL = "https://api.moolre.com"

#: Moolre's numeric channel codes for Ghana mobile money.
CHANNELS = {
    MomoNetwork.MTN: "13",
    MomoNetwork.TELECEL: "6",
    MomoNetwork.AT: "7",
}

PROMPT_SENT = "TR099"
OTP_SENT = "TP14"
OTP_ACCEPTED = "TP17"
OTP_WRONG = "TP15"  # seen in the sandbox; not in the published code list

#: The status endpoint's data.txstatus.
TX_SUCCESS, TX_PENDING, TX_FAILED = 1, 0, 2

PROMPT_INSTRUCTIONS = (
    "Approve the prompt on your phone and enter your Mobile Money PIN. "
    "Your network adds a small fee to the amount shown."
)
OTP_INSTRUCTIONS = (
    "We have sent you a verification code by SMS. Enter it here to receive the payment prompt."
)


def local_number(phone: str) -> str:
    """+233241234567 -> 0241234567, the format Moolre's payer field takes."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("233") and len(digits) == 12:
        return "0" + digits[3:]
    return digits if digits.startswith("0") else ("0" + digits if digits else "")


def _money(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount.quantize(Decimal("0.01"))


class MoolreProvider(PaymentProvider):
    key = "moolre"
    display_name = "Moolre Mobile Money"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)
    customer_fee_note = (
        "Your network adds a fee of about 1% to the prompt - GH₵10.00 shows as about "
        "GH₵10.10. Your wallet is credited the full amount you enter."
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PAYMENT_CREDENTIALS.get("moolre", {})
        self.username = str(credentials.get("username") or "")
        self.public_key = str(credentials.get("public_key") or "")
        self.account_number = str(credentials.get("account_number") or "")
        self.callback_secret = str(credentials.get("callback_secret") or "")
        self.base_url = str(credentials.get("base_url") or LIVE_BASE_URL).rstrip("/")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.account_number and self.callback_secret
                    and (self.public_key or self.base_url != LIVE_BASE_URL))

    # -- transport -------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        if not self.is_configured:
            raise ServiceUnavailable("Mobile Money payments are not available right now.",
                                     code="PAYMENT_PROVIDER_NOT_CONFIGURED")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "X-API-USER": self.username}
        if self.public_key:
            headers["X-API-PUBKEY"] = self.public_key
        try:
            response = self._session.post(f"{self.base_url}{path}", json=body, headers=headers,
                                          timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            # Not a failure: the request may have been taken. Reconciliation by
            # externalref decides, never this path.
            logger.warning("moolre_timeout", extra={"path": path})
            raise ProviderError("The payment provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("moolre_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the payment provider.") from exc

        if response.status_code == 429:
            raise ServiceUnavailable("The payment provider is busy. Please try again shortly.",
                                     code="PAYMENT_PROVIDER_RATE_LIMITED")
        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("moolre_unreadable_response", extra={"status": response.status_code})
            raise ProviderError("The payment provider returned an unreadable response.") from exc
        if not isinstance(payload, dict):
            raise ProviderError("The payment provider returned an unreadable response.")
        return payload

    @staticmethod
    def _code(payload: dict) -> str:
        return str(payload.get("code") or "")

    @staticmethod
    def _ok(payload: dict) -> bool:
        return str(payload.get("status")) == "1"

    def _refuse(self, payload: dict, what: str, reference: str) -> ProviderError:
        # The provider's wording is for staff, never the customer.
        logger.error("moolre_error", extra={
            "operation": what, "reference": reference, "provider_code": self._code(payload)[:20],
            "provider_message": str(payload.get("message") or "")[:200],
        })
        error = ProviderError("The payment could not be started. Please try again.")
        error.provider_code = self._code(payload)
        return error

    # -- charges ---------------------------------------------------------

    def _collect(self, *, amount, phone: str, network: str, reference: str,
                 otp: str = "") -> dict:
        channel = CHANNELS.get(network)
        if channel is None:
            raise ProviderError("That mobile money network is not supported yet.")
        body = {
            "type": 1, "channel": channel, "currency": "GHS",
            "payer": local_number(phone), "amount": f"{Decimal(amount):.2f}",
            "externalref": reference, "accountnumber": self.account_number,
        }
        if otp:
            body["otpcode"] = otp
        return self._post("/open/transact/payment", body)

    def _from_collect(self, payload: dict, reference: str, amount) -> ChargeDTO:
        code = self._code(payload)
        if self._ok(payload) and code == PROMPT_SENT:
            return ChargeDTO(provider_reference=reference, status=ChargeStatus.PHONE_AUTH_REQUIRED,
                             amount=amount, instructions=PROMPT_INSTRUCTIONS,
                             raw={"status": code, "moolre_id": str(payload.get("data") or "")[:64]})
        if self._ok(payload) and code == OTP_SENT:
            return ChargeDTO(provider_reference=reference, status=ChargeStatus.OTP_REQUIRED,
                             amount=amount, instructions=OTP_INSTRUCTIONS, raw={"status": code})
        raise self._refuse(payload, "collect", reference)

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        logger.info("moolre_charge_initiating", extra={
            "reference": reference, "network": network, "phone": mask_phone(phone)})
        payload = self._collect(amount=amount, phone=phone, network=network, reference=reference)
        return self._from_collect(payload, reference, amount)

    def submit_otp(self, *, reference: str, otp: str) -> ChargeDTO:
        """Verify the payer's number with Moolre's SMS code, then send the prompt.

        The flow needs the original request again, so it is read from our own
        payment record. The code is never logged.
        """
        from apps.payments.models import Payment

        payment = Payment.objects.filter(reference=reference, provider=self.key).first()
        if payment is None:
            raise ProviderError("We could not find that payment.")
        common = {"amount": payment.amount, "phone": payment.phone, "network": payment.network,
                  "reference": payment.reference}

        verified = self._collect(otp=otp, **common)
        code = self._code(verified)
        if code == PROMPT_SENT and self._ok(verified):
            return self._from_collect(verified, payment.reference, payment.amount)
        if not (self._ok(verified) and code == OTP_ACCEPTED):
            logger.info("moolre_otp_refused", extra={"reference": reference,
                                                     "provider_code": code[:20]})
            error = ProviderError("That code was not accepted.")
            error.provider_code = code
            raise error
        logger.info("moolre_otp_accepted", extra={"reference": reference})
        return self._from_collect(self._collect(**common), payment.reference, payment.amount)

    def fetch_charge(self, reference: str) -> ChargeDTO:
        payload = self._post("/open/transact/status", {
            "type": 1, "idtype": 1, "id": reference, "accountnumber": self.account_number})
        data = payload.get("data")
        if not self._ok(payload) or not isinstance(data, dict):
            raise self._refuse(payload, "status", reference)
        if str(data.get("externalref") or "") != reference:
            # Never settle one payment with another's answer.
            raise self._refuse(payload, "status-mismatch", reference)
        try:
            txstatus = int(data.get("txstatus"))
        except (TypeError, ValueError):
            txstatus = TX_PENDING
        status = {TX_SUCCESS: ChargeStatus.SUCCESS,
                  TX_FAILED: ChargeStatus.FAILED}.get(txstatus, ChargeStatus.PROCESSING)
        return ChargeDTO(
            provider_reference=reference, status=status,
            amount=_money(data.get("amount")) if status == ChargeStatus.SUCCESS else None,
            failure_reason=(str(data.get("reason") or "The payment was not completed.")[:200]
                            if status == ChargeStatus.FAILED else ""),
            raw={"status": str(txstatus), "code": self._code(payload)[:20],
                 "transactionid": str(data.get("transactionid") or "")[:40]},
        )

    # -- callbacks -------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        """The body's secret against the wallet's, in constant time.

        A weak proof, which is why parse_webhook settles nothing on its word.
        """
        if not self.callback_secret:
            logger.error("moolre_webhook_no_secret")
            return False
        try:
            data = (json.loads(raw_body.decode("utf-8")) or {}).get("data") or {}
        except (ValueError, UnicodeDecodeError, AttributeError):
            return False
        provided = str(data.get("secret") or "") if isinstance(data, dict) else ""
        ok = bool(provided) and hmac.compare_digest(provided, self.callback_secret)
        if not ok:
            logger.error("moolre_webhook_bad_secret")
        return ok

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        """A callback is a prompt: the status endpoint says what happened."""
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            data = payload.get("data") or {}
            reference = str(data.get("externalref") or "")
        except (ValueError, UnicodeDecodeError, AttributeError) as exc:
            raise ProviderError("Unreadable webhook payload.") from exc
        if not reference:
            raise ProviderError("The callback carries no external reference.")

        claimed = str(payload.get("code") or "")
        try:
            confirmed = self.fetch_charge(reference)
            status, amount = confirmed.status, confirmed.amount
            reason = confirmed.failure_reason
        except (ProviderError, ServiceUnavailable):
            # Could not confirm: record it and change nothing. The reconcile
            # sweep asks again shortly.
            logger.warning("moolre_webhook_unconfirmed", extra={"reference": reference})
            status, amount, reason = ChargeStatus.PROCESSING, None, ""

        return WebhookEventDTO(
            event_id=derive("moolre", reference, claimed, status.value,
                            str(data.get("transactionid") or "")),
            event_type=f"payment.{claimed or 'unknown'}",
            reference=reference, provider_reference=reference, status=status,
            amount=amount, failure_reason=reason,
            # Kept small but replayable: parse_webhook_payload re-reads it.
            raw={"code": claimed, "data": {"externalref": reference,
                                           "transactionid": data.get("transactionid")}},
        )

    def health_check(self) -> bool:
        return self.is_configured
