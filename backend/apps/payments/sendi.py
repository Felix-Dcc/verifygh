"""SENDI Payments adapter (hosted checkout, card and mobile money).

8 Oct 2026: a stopgap while Moolre approves the wallet. Built from the Merchant
API page in the SENDI dashboard (mesendi.com/app/api, "Docs" tab) and the
"Merchant API Integration Guide" PDF it generates (both read 8 Oct 2026), and
nothing else. SENDI is a product of Stelnex (S.TFIX Media).

    POST /api/v1/charge/initialize   - Bearer secret key, Idempotency-Key;
                                       body amount_cents, currency,
                                       customer_email, description,
                                       callback_url, metadata. Answers
                                       data.reference (ch_...) and
                                       data.authorization_url
    GET  /api/v1/charge/verify?reference=ch_...  - the charge's status
    webhook                          - X-Sendi-Signature: hex HMAC-SHA512 of
                                       the raw body, keyed by the signing secret

The customer pays on SENDI's own page (authorization_url) and comes back to
callback_url; nothing they bring back is trusted.

What the docs do NOT spell out is the verify response beyond `status` and the
webhook body's fields. So, as with Moolre:

* a webhook is only a prompt - verify is asked, and only its answer settles;
* SUCCESS needs every check to pass: the same ch_ reference, GHS, a readable
  amount_cents, and not a test-mode charge on a live key. Anything less is held
  as PROCESSING for the sweep and for staff, never credited on a guess;
* statuses other than success/failed/abandoned/cancelled/expired stay pending,
  and the expiry sweep closes them out after asking verify one last time.

Test keys (sk_test_) complete without money moving, so production refuses them
(config/settings/prod.py) and a live key never credits a test-mode charge.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib.parse import urlparse

import requests
from django.conf import settings

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError, ServiceUnavailable
from apps.common.idempotency import derive
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.sendi")

REQUEST_TIMEOUT = 25
LIVE_BASE_URL = "https://mesendi.com/backend"
#: The only host a customer is ever sent to for checkout.
CHECKOUT_HOST = "mesendi.com"

_STATUSES = {
    "success": ChargeStatus.SUCCESS,
    "failed": ChargeStatus.FAILED,
    "abandoned": ChargeStatus.CANCELLED,
    "cancelled": ChargeStatus.CANCELLED,
    "expired": ChargeStatus.EXPIRED,
}

CHECKOUT_INSTRUCTIONS = (
    "Finish paying on the SENDI checkout page. We credit your wallet as soon as SENDI confirms it."
)


def safe_checkout_url(url: str) -> str:
    """The URL if it is an https page on SENDI's own host, else ""."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""
    if parsed.scheme == "https" and parsed.hostname == CHECKOUT_HOST:
        return parsed.geturl()
    return ""


class SendiProvider(PaymentProvider):
    key = "sendi"
    display_name = "SENDI checkout"
    #: SENDI's page takes the payment method itself; the number on our form is
    #: kept for support, not charged.
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)
    hosted_checkout = True
    customer_fee_note = (
        "You'll finish paying on SENDI's secure checkout page. SENDI adds a 1.4% fee there - "
        "GH₵10.00 costs about GH₵10.14. Your wallet is credited the full amount you enter."
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PAYMENT_CREDENTIALS.get("sendi", {})
        self.secret_key = str(credentials.get("secret_key") or "")
        self.webhook_secret = str(credentials.get("webhook_secret") or "")
        self.base_url = str(credentials.get("base_url") or LIVE_BASE_URL).rstrip("/")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.secret_key and self.webhook_secret)

    @property
    def live(self) -> bool:
        return self.secret_key.startswith("sk_live_")

    # -- transport -------------------------------------------------------

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 params: dict | None = None, idempotency_key: str = "") -> dict:
        if not self.is_configured:
            raise ServiceUnavailable("Payments are not available right now.",
                                     code="PAYMENT_PROVIDER_NOT_CONFIGURED")
        headers = {"Authorization": f"Bearer {self.secret_key}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._session.request(method, f"{self.base_url}{path}", json=body,
                                             params=params, headers=headers,
                                             timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            logger.warning("sendi_timeout", extra={"path": path})
            raise ProviderError("The payment provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("sendi_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the payment provider.") from exc

        if response.status_code == 429:
            raise ServiceUnavailable("The payment provider is busy. Please try again shortly.",
                                     code="PAYMENT_PROVIDER_RATE_LIMITED")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400 or not isinstance(payload, dict) \
                or payload.get("success") is False:
            # SENDI's wording is for staff, never the customer.
            message = payload.get("message") if isinstance(payload, dict) else ""
            logger.error("sendi_error", extra={"path": path, "status": response.status_code,
                                               "provider_message": str(message or "")[:200]})
            error = ProviderError("The payment could not be started. Please try again.")
            error.provider_code = str(response.status_code)
            raise error
        return payload

    # -- charges ---------------------------------------------------------

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        frontend = settings.VERIFYGH["FRONTEND_URL"].rstrip("/")
        payload = self._request("POST", "/api/v1/charge/initialize", idempotency_key=reference,
                                body={
            "amount_cents": int((Decimal(amount) * 100).to_integral_value()),
            "currency": "GHS",
            "customer_email": email,
            "description": f"VerifyGH wallet top-up {reference}",
            "callback_url": f"{frontend}/wallet/deposit?reference={reference}",
            "metadata": {"reference": reference},
        })
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        charge_ref = str(data.get("reference") or "")
        checkout = safe_checkout_url(data.get("authorization_url"))
        if not charge_ref or not checkout:
            logger.error("sendi_initialize_incomplete", extra={
                "reference": reference, "has_reference": bool(charge_ref),
                "checkout_host_ok": bool(checkout)})
            raise ProviderError("The payment could not be started. Please try again.")
        logger.info("sendi_charge_created", extra={"reference": reference,
                                                   "charge": charge_ref[:40]})
        return ChargeDTO(provider_reference=charge_ref, status=ChargeStatus.PENDING,
                         amount=amount, instructions=CHECKOUT_INSTRUCTIONS,
                         redirect_url=checkout,
                         raw={"status": str(data.get("status") or "pending")[:40]})

    def _charge_ref(self, reference: str) -> str:
        from apps.payments.models import Payment

        payment = Payment.objects.filter(reference=reference, provider=self.key) \
            .only("provider_reference").first()
        if payment is None or not payment.provider_reference:
            raise ProviderError("We could not find that payment.")
        return payment.provider_reference

    def fetch_charge(self, reference: str) -> ChargeDTO:
        charge_ref = self._charge_ref(reference)
        payload = self._request("GET", "/api/v1/charge/verify", params={"reference": charge_ref})
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError("The payment provider returned an unreadable response.")

        said = str(data.get("status") or "").strip().lower()
        status = _STATUSES.get(said, ChargeStatus.PENDING)
        raw = {"status": said[:40], "charge": charge_ref[:40]}
        amount = None

        if status == ChargeStatus.SUCCESS:
            problem = self._success_problem(data, charge_ref)
            if problem:
                # Never credit on a doubtful success: hold it for the sweep
                # and for staff, who can see the reason in the logs.
                logger.error("sendi_success_held", extra={"reference": reference,
                                                          "problem": problem})
                return ChargeDTO(provider_reference=charge_ref, status=ChargeStatus.PROCESSING,
                                 raw={**raw, "held": problem})
            amount = (Decimal(int(data["amount_cents"])) / 100).quantize(Decimal("0.01"))

        return ChargeDTO(
            provider_reference=charge_ref, status=status, amount=amount,
            failure_reason=("The payment was not completed."
                            if status in (ChargeStatus.FAILED, ChargeStatus.CANCELLED,
                                          ChargeStatus.EXPIRED) else ""),
            raw=raw,
        )

    def _success_problem(self, data: dict, charge_ref: str) -> str:
        if str(data.get("reference") or "") != charge_ref:
            return "reference-mismatch"
        if str(data.get("currency") or "GHS").upper() != "GHS":
            return "currency"
        try:
            cents = int(data.get("amount_cents"))
        except (TypeError, ValueError):
            return "no-amount"
        if cents <= 0:
            return "no-amount"
        test_charge = bool(data.get("test_mode")) or charge_ref.startswith("ch_test_")
        if self.live and test_charge:
            return "test-charge-on-live-key"
        return ""

    # -- webhooks --------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        if not self.webhook_secret:
            logger.error("sendi_webhook_no_secret")
            return False
        provided = str(headers.get("x-sendi-signature") or "").strip().lower()
        expected = hmac.new(self.webhook_secret.encode("utf-8"), raw_body,
                            hashlib.sha512).hexdigest()
        ok = bool(provided) and hmac.compare_digest(provided, expected)
        if not ok:
            logger.error("sendi_webhook_bad_signature")
        return ok

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        """A webhook is a prompt: verify says what happened."""
        from apps.payments.models import Payment

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("Unreadable webhook payload.") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Unreadable webhook payload.")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        charge_ref = str(data.get("reference") or "")
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

        payment = None
        if charge_ref:
            payment = Payment.objects.filter(provider=self.key,
                                             provider_reference=charge_ref).first()
        if payment is None and meta.get("reference"):
            payment = Payment.objects.filter(provider=self.key,
                                             reference=str(meta["reference"])).first()
        if payment is None:
            # Kept as unparsed, where the admin health check shows it.
            raise ProviderError("The webhook names no payment of ours.")

        claimed = str(payload.get("event") or data.get("status") or "")[:40]
        try:
            confirmed = self.fetch_charge(payment.reference)
            status, amount, reason = confirmed.status, confirmed.amount, confirmed.failure_reason
        except (ProviderError, ServiceUnavailable):
            logger.warning("sendi_webhook_unconfirmed", extra={"reference": payment.reference})
            status, amount, reason = ChargeStatus.PROCESSING, None, ""

        return WebhookEventDTO(
            event_id=derive("sendi", payment.provider_reference, claimed, status.value),
            event_type=f"charge.{claimed or 'unknown'}",
            reference=payment.reference, provider_reference=payment.provider_reference,
            status=status, amount=amount, failure_reason=reason,
            # Small but replayable: parse_webhook_payload re-reads it.
            raw={"event": claimed, "data": {"reference": payment.provider_reference,
                                            "metadata": {"reference": payment.reference}}},
        )

    def health_check(self) -> bool:
        return self.is_configured
