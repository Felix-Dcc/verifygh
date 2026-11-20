"""MojoPay Omni adapter (Ghana mobile money, prompt on the payer's phone).

19 Nov 2026: replaces SENDI while SENDI has problems. Built from MojoPay's own
docs, read 19 Nov 2026, and nothing else: the OpenAPI spec
(omni.mojo-pay.com/doc/openapi.yaml), the sample payloads
(/doc/samples.json) and the integration guide (/doc/payments).

    POST /v1/oauth/token        - client_id + client_secret -> Bearer token,
                                  expires_in 1200 s
    POST /v1/collections        - Idempotency-Key; amount (string), currency,
                                  merchant_reference, mobile (233...), provider
                                  (MTN | VODAFONE | AIRTELTIGO). Answers the
                                  collection: id CL_..., status "processing"
    GET  /v1/collections?merchant_reference=...  - the collection's status
    webhook                     - MojoPay-Signature: t=<unix>,v1=<hex>, the hex
                                  being HMAC-SHA256 of "{t}.{raw_body}" keyed by
                                  the API client's webhook secret; reject t
                                  outside +-300 s

Fees are "on_top" by default: the payer pays amount + fee, and `amount` (the
principal) is what reaches us - so `amount` is what we credit.

As for SENDI and Moolre, a webhook is only a prompt: the collection is fetched
and only that answer settles. SUCCESS needs our reference, GHS and a readable
amount; anything less is held for staff, never credited on a guess.

While the merchant is in MojoPay's Testing mode, collections are real money
but capped (GH₵5 in Ghana) until "Go Live" in the portal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError, ServiceUnavailable
from apps.common.idempotency import derive
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.mojopay")

REQUEST_TIMEOUT = 25
LIVE_BASE_URL = "https://omni.mojo-pay.com"
SIGNATURE_TOLERANCE = 300
_TOKEN_CACHE_KEY = "payments:mojopay:token"

#: MojoPay's provider codes (GET /v1/metadata/mobile_providers).
PROVIDERS = {
    MomoNetwork.MTN: "MTN",
    MomoNetwork.TELECEL: "VODAFONE",
    MomoNetwork.AT: "AIRTELTIGO",
}

_STATUSES = {
    "succeeded": ChargeStatus.SUCCESS,
    "failed": ChargeStatus.FAILED,
    "cancelled": ChargeStatus.CANCELLED,
    "expired": ChargeStatus.EXPIRED,
    "processing": ChargeStatus.PROCESSING,
}

PROMPT_INSTRUCTIONS = (
    "Approve the prompt on your phone and enter your Mobile Money PIN. "
    "If no prompt appears, check your approvals menu (MTN: dial *170#, then My Approvals)."
)


def msisdn(phone: str) -> str:
    """+233241234567 or 0241234567 -> 233241234567, the format MojoPay takes."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "233" + digits[1:]
    return digits


def _money(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 else None


class MojoPayProvider(PaymentProvider):
    key = "mojopay"
    display_name = "MojoPay Mobile Money"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)
    # 1.98% "on_top", as quoted by MojoPay after Go Live (20 Nov 2026).
    customer_fee_note = (
        "MojoPay adds a 1.98% fee to the prompt on your phone - GH₵15.00 shows as GH₵15.29. "
        "Your wallet is credited the full amount you enter."
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PAYMENT_CREDENTIALS.get("mojopay", {})
        self.client_id = str(credentials.get("client_id") or "")
        self.client_secret = str(credentials.get("client_secret") or "")
        self.webhook_secret = str(credentials.get("webhook_secret") or "")
        self.base_url = str(credentials.get("base_url") or LIVE_BASE_URL).rstrip("/")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.webhook_secret)

    # -- transport -------------------------------------------------------

    def _send(self, method: str, path: str, *, headers: dict, body: dict | None = None,
              params: dict | None = None) -> requests.Response:
        try:
            return self._session.request(method, f"{self.base_url}{path}", json=body,
                                         params=params, headers=headers,
                                         timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            # Not a failure: the request may have been taken. Reconciliation by
            # merchant_reference decides.
            logger.warning("mojopay_timeout", extra={"path": path})
            raise ProviderError("The payment provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("mojopay_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the payment provider.") from exc

    def _token(self, *, fresh: bool = False) -> str:
        if not fresh:
            cached = cache.get(_TOKEN_CACHE_KEY)
            if cached:
                return cached
        response = self._send("POST", "/v1/oauth/token", headers={
            "Content-Type": "application/json", "Accept": "application/json"}, body={
            "grant_type": "client_credentials", "client_id": self.client_id,
            "client_secret": self.client_secret})
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        token = str(payload.get("access_token") or "") if isinstance(payload, dict) else ""
        if response.status_code >= 400 or not token:
            logger.error("mojopay_token_refused", extra={"status": response.status_code})
            raise ServiceUnavailable("Payments are not available right now.",
                                     code="PAYMENT_PROVIDER_AUTH_FAILED")
        try:
            lifetime = int(payload.get("expires_in") or 0)
        except (TypeError, ValueError):
            lifetime = 0
        # A minute's margin, so a token never expires mid-request.
        cache.set(_TOKEN_CACHE_KEY, token, max(lifetime - 60, 60))
        return token

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 params: dict | None = None, idempotency_key: str = "") -> tuple[int, dict]:
        if not self.is_configured:
            raise ServiceUnavailable("Payments are not available right now.",
                                     code="PAYMENT_PROVIDER_NOT_CONFIGURED")
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._token(fresh=attempt == 2)}",
                       "Accept": "application/json", "Content-Type": "application/json"}
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            response = self._send(method, path, headers=headers, body=body, params=params)
            if response.status_code != 401:
                break
            cache.delete(_TOKEN_CACHE_KEY)  # expired early; one retry with a new token

        if response.status_code == 429:
            raise ServiceUnavailable("The payment provider is busy. Please try again shortly.",
                                     code="PAYMENT_PROVIDER_RATE_LIMITED")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {}
        return response.status_code, payload

    @staticmethod
    def _error(payload: dict) -> tuple[str, str]:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        return str(error.get("code") or "")[:60], str(error.get("request_id") or "")[:40]

    # -- charges ---------------------------------------------------------

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        provider = PROVIDERS.get(network)
        if provider is None:
            raise ProviderError("This network is not supported.")
        status_code, payload = self._request(
            "POST", "/v1/collections", idempotency_key=reference, body={
                "amount": f"{Decimal(amount).quantize(Decimal('0.01'))}",
                "currency": "GHS",
                "merchant_reference": reference,
                "mobile": msisdn(phone),
                "provider": provider,
                "description": f"VerifyGH wallet top-up {reference}",
            })
        collection_id = str(payload.get("id") or "")
        if status_code >= 400 or not collection_id:
            code, request_id = self._error(payload)
            # MojoPay's wording is for staff, never the customer.
            logger.error("mojopay_collection_refused", extra={
                "reference": reference, "status": status_code, "error_code": code,
                "request_id": request_id})
            error = ProviderError("The payment could not be started. Please try again.")
            error.provider_code = code or str(status_code)
            raise error

        said = str(payload.get("status") or "").lower()
        status = _STATUSES.get(said, ChargeStatus.PENDING)
        if status in (ChargeStatus.PROCESSING, ChargeStatus.PENDING):
            status = ChargeStatus.PHONE_AUTH_REQUIRED
        logger.info("mojopay_collection_created", extra={"reference": reference,
                                                         "collection": collection_id[:40]})
        return ChargeDTO(provider_reference=collection_id, status=status, amount=amount,
                         instructions=PROMPT_INSTRUCTIONS,
                         failure_reason=("The payment was not completed."
                                         if status == ChargeStatus.FAILED else ""),
                         raw={"status": said[:40]})

    def fetch_charge(self, reference: str) -> ChargeDTO:
        status_code, data = self._request("GET", "/v1/collections",
                                          params={"merchant_reference": reference})
        if status_code == 404:
            # Not there (yet): never failed on a guess - the expiry sweep closes it.
            return ChargeDTO(provider_reference="", status=ChargeStatus.PENDING,
                             raw={"status": "not-found"})
        if status_code >= 400 or not data:
            code, request_id = self._error(data)
            logger.error("mojopay_fetch_failed", extra={"reference": reference,
                                                        "status": status_code,
                                                        "error_code": code,
                                                        "request_id": request_id})
            raise ProviderError("The payment provider returned an unreadable response.")

        collection_id = str(data.get("id") or "")
        said = str(data.get("status") or "").strip().lower()
        status = _STATUSES.get(said, ChargeStatus.PENDING)
        raw = {"status": said[:40], "collection": collection_id[:40]}
        amount = None

        if status == ChargeStatus.SUCCESS:
            problem = self._success_problem(data, reference)
            if problem:
                logger.error("mojopay_success_held", extra={"reference": reference,
                                                            "problem": problem})
                return ChargeDTO(provider_reference=collection_id,
                                 status=ChargeStatus.PROCESSING, raw={**raw, "held": problem})
            amount = _money(data.get("amount"))

        return ChargeDTO(
            provider_reference=collection_id, status=status, amount=amount,
            failure_reason=(str(data.get("status_detail") or "The payment was not completed.")[:200]
                            if status in (ChargeStatus.FAILED, ChargeStatus.CANCELLED,
                                          ChargeStatus.EXPIRED) else ""),
            raw=raw,
        )

    @staticmethod
    def _success_problem(data: dict, reference: str) -> str:
        if str(data.get("merchant_reference") or "") != reference:
            return "reference-mismatch"
        if str(data.get("currency") or "").upper() != "GHS":
            return "currency"
        if _money(data.get("amount")) is None:
            return "no-amount"
        return ""

    # -- webhooks --------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        if not self.webhook_secret:
            logger.error("mojopay_webhook_no_secret")
            return False
        parts = dict(part.strip().split("=", 1)
                     for part in str(headers.get("mojopay-signature") or "").split(",")
                     if "=" in part)
        stamp, provided = parts.get("t", ""), parts.get("v1", "").lower()
        try:
            fresh = abs(time.time() - int(stamp)) <= SIGNATURE_TOLERANCE
        except ValueError:
            fresh = False
        expected = hmac.new(self.webhook_secret.encode("utf-8"),
                            stamp.encode("utf-8") + b"." + raw_body,
                            hashlib.sha256).hexdigest()
        ok = fresh and bool(provided) and hmac.compare_digest(provided, expected)
        if not ok:
            logger.error("mojopay_webhook_rejected", extra={"stale": not fresh})
        return ok

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        """A webhook is a prompt: the collection itself says what happened."""
        from apps.payments.models import Payment

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("Unreadable webhook payload.") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        obj = data.get("object") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            raise ProviderError("Unreadable webhook payload.")

        reference = str(obj.get("merchant_reference") or "")
        payment = Payment.objects.filter(provider=self.key, reference=reference).first() \
            if reference else None
        if payment is None:
            # Kept as unparsed, where the admin health check shows it.
            raise ProviderError("The webhook names no payment of ours.")

        claimed = str(payload.get("type") or "")[:60]
        try:
            confirmed = self.fetch_charge(payment.reference)
            status, amount, reason = confirmed.status, confirmed.amount, confirmed.failure_reason
        except (ProviderError, ServiceUnavailable):
            logger.warning("mojopay_webhook_unconfirmed", extra={"reference": payment.reference})
            status, amount, reason = ChargeStatus.PROCESSING, None, ""

        collection_id = str(obj.get("id") or payment.provider_reference or "")[:60]
        return WebhookEventDTO(
            event_id=derive("mojopay", collection_id, claimed, status.value),
            event_type=claimed or "collection.unknown",
            reference=payment.reference, provider_reference=collection_id,
            status=status, amount=amount, failure_reason=reason,
            # Small but replayable: parse_webhook_payload re-reads it.
            raw={"type": claimed, "data": {"object": {"id": collection_id,
                                                      "merchant_reference": payment.reference}}},
        )

    def health_check(self) -> bool:
        return self.is_configured
