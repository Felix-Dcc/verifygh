"""TextVerified adapter - structure complete, endpoints intentionally blank.

READ THIS BEFORE FILLING IT IN
------------------------------
Integration with TextVerified must go through their **official API** under an
account or reseller arrangement that permits reselling. This adapter therefore:

* makes plain authenticated HTTPS calls and nothing else;
* does not scrape any page, drive a browser, or touch a login form;
* does not attempt to bypass authentication, CAPTCHAs, rate limits, payment
  controls or any other protection;
* rate-limits itself and backs off on 429 rather than retrying through it.

Every endpoint path, request body and response field below is left as a
`TODO(credentials)` constant. They are deliberately **not guessed** - inventing
an endpoint produces code that looks finished and fails in production. Fill each
one in from the official API documentation, then run the contract tests in
`tests/test_provider_contract.py` against a sandbox key.

Until then, keep VERIFICATION_PROVIDER=mock.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import requests
from django.conf import settings

from apps.common.errors import ProviderError, ServiceUnavailable
from apps.verification.base import (
    AvailabilityDTO,
    CodeDTO,
    ProviderCountryDTO,
    ProviderOrderDTO,
    ProviderOrderState,
    ProviderServiceDTO,
    VerificationProvider,
)

logger = logging.getLogger("verifygh.provider.textverified")

REQUEST_TIMEOUT = 20


class _NotConfigured(ServiceUnavailable):
    code = "PROVIDER_NOT_CONFIGURED"
    message = "This provider is not available yet."


class TextVerifiedProvider(VerificationProvider):
    key = "textverified"
    display_name = "TextVerified"

    #: Set from the Provider row / agreement, not assumed.
    permits_code_display = True
    supports_webhooks = False

    # ------------------------------------------------------------------
    # TODO(credentials): fill these in from the official API documentation.
    # Leave as empty strings until you have the docs in front of you.
    # ------------------------------------------------------------------
    BASE_URL = ""            # e.g. "https://www.textverified.com/api/..." - confirm in docs
    PATH_TOKEN = ""          # auth/token endpoint
    PATH_SERVICES = ""       # list of services
    PATH_COUNTRIES = ""      # list of countries/areas
    PATH_PRICING = ""        # pricing lookup
    PATH_AVAILABILITY = ""   # stock/availability lookup
    PATH_CREATE_ORDER = ""   # create a verification
    PATH_ORDER_STATUS = ""   # fetch one verification (format with the id)
    PATH_ORDER_CANCEL = ""   # cancel a verification
    PATH_ORDER_REFUND = ""   # request a refund
    # ------------------------------------------------------------------

    #: Maps the provider's own status strings onto our normalised states.
    #: TODO(credentials): confirm the exact strings the API returns.
    STATE_MAP: dict[str, ProviderOrderState] = {}

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PROVIDER_CREDENTIALS.get("textverified", {})
        self.api_key = credentials.get("api_key", "")
        self.api_username = credentials.get("api_username", "")
        self.base_url = (credentials.get("base_url") or self.BASE_URL).rstrip("/")
        self._session = requests.Session()
        self._bearer: str | None = None

    # -- plumbing --------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _require_configured(self, what: str) -> None:
        if not self.is_configured:
            logger.error("provider_not_configured", extra={"operation": what})
            raise _NotConfigured()

    def _require_path(self, path: str, what: str) -> str:
        if not path:
            raise _NotConfigured(
                f"The TextVerified endpoint for {what} has not been configured yet."
            )
        return f"{self.base_url}{path}"

    def _headers(self) -> dict:
        # TODO(credentials): confirm whether the API uses a bearer token obtained
        # from PATH_TOKEN, or the API key directly. Both shapes are supported here.
        token = self._bearer or self.api_key
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "VerifyGH/1.0 (+authorized reseller integration)",
        }

    def _request(self, method: str, url: str, **kwargs):
        """One HTTP call, with the provider's rate limits respected.

        A 429 is surfaced as a retryable error and never retried in a tight
        loop - the caller backs off. We do not work around rate limiting.
        """
        try:
            response = self._session.request(
                method, url, headers=self._headers(), timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.Timeout as exc:
            logger.warning("provider_timeout", extra={"url": url})
            raise ProviderError("The provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("provider_transport_error", extra={"url": url})
            raise ProviderError("We could not reach the provider.") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            logger.warning("provider_rate_limited", extra={"retry_after": retry_after})
            raise ServiceUnavailable(
                "The provider is busy. Please try again shortly.",
                code="PROVIDER_RATE_LIMITED",
                details={"retry_after": retry_after},
            )
        if response.status_code in (401, 403):
            # Never surfaced to the user beyond a generic message.
            logger.error("provider_auth_failed", extra={"status": response.status_code})
            raise ProviderError("The provider rejected our credentials.")
        if response.status_code >= 400:
            logger.error(
                "provider_http_error",
                extra={"status": response.status_code, "url": url},
            )
            raise ProviderError("The provider returned an error.")

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("The provider returned an unreadable response.") from exc

    def _map_state(self, raw_state: str) -> ProviderOrderState:
        if not self.STATE_MAP:
            raise _NotConfigured(
                "The TextVerified status mapping has not been configured yet."
            )
        mapped = self.STATE_MAP.get(str(raw_state).lower())
        if mapped is None:
            logger.error("provider_unknown_state", extra={"raw_state": raw_state})
            raise ProviderError("The provider returned a status we do not recognise.")
        return mapped

    # -- catalog ---------------------------------------------------------

    def get_services(self) -> list[ProviderServiceDTO]:
        self._require_configured("get_services")
        url = self._require_path(self.PATH_SERVICES, "listing services")
        payload = self._request("GET", url)
        return self._parse_services(payload)

    def _parse_services(self, payload) -> list[ProviderServiceDTO]:
        # TODO(credentials): map the documented response onto ProviderServiceDTO.
        raise _NotConfigured("The TextVerified service response mapping is not implemented.")

    def get_countries(self) -> list[ProviderCountryDTO]:
        self._require_configured("get_countries")
        url = self._require_path(self.PATH_COUNTRIES, "listing countries")
        payload = self._request("GET", url)
        return self._parse_countries(payload)

    def _parse_countries(self, payload) -> list[ProviderCountryDTO]:
        # TODO(credentials): map the documented response onto ProviderCountryDTO.
        raise _NotConfigured("The TextVerified country response mapping is not implemented.")

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        self._require_configured("get_pricing")
        url = self._require_path(self.PATH_PRICING, "pricing")
        self._request("GET", url, params={"service": service_code, "country": country_code})
        # TODO(credentials): read the documented price field off the response.
        raise _NotConfigured("The TextVerified pricing response mapping is not implemented.")

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        self._require_configured("get_availability")
        url = self._require_path(self.PATH_AVAILABILITY, "availability")
        self._request("GET", url, params={"service": service_code, "country": country_code})
        # TODO(credentials): read the documented availability field off the response.
        raise _NotConfigured("The TextVerified availability mapping is not implemented.")

    # -- orders ----------------------------------------------------------

    def create_order(
        self, service_code: str, country_code: str, idempotency_key: str
    ) -> ProviderOrderDTO:
        self._require_configured("create_order")
        url = self._require_path(self.PATH_CREATE_ORDER, "creating an order")
        # TODO(credentials): confirm the documented request body, and whether the
        # API accepts an idempotency key. If it does not, reconcile duplicates in
        # apps/orders/tasks.py instead of retrying blindly.
        self._request(
            "POST",
            url,
            json={"service": service_code, "country": country_code},
            headers={**self._headers(), "Idempotency-Key": idempotency_key},
        )
        raise _NotConfigured("The TextVerified create-order mapping is not implemented.")

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        self._require_configured("get_order_status")
        template = self._require_path(self.PATH_ORDER_STATUS, "order status")
        self._request("GET", template.format(id=provider_order_id))
        raise _NotConfigured("The TextVerified order-status mapping is not implemented.")

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        status = self.get_order_status(provider_order_id)
        return status.code

    def cancel_order(self, provider_order_id: str) -> bool:
        self._require_configured("cancel_order")
        template = self._require_path(self.PATH_ORDER_CANCEL, "cancelling an order")
        self._request("POST", template.format(id=provider_order_id))
        return True

    def refund_order(self, provider_order_id: str) -> bool:
        self._require_configured("refund_order")
        template = self._require_path(self.PATH_ORDER_REFUND, "refunding an order")
        self._request("POST", template.format(id=provider_order_id))
        return True

    def health_check(self) -> bool:
        return self.is_configured
