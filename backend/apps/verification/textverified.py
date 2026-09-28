"""TextVerified adapter, built from their published OpenAPI v2 specification.

Source of truth: https://backend.textverified.com/swagger/v2/swagger.json
(rendered at https://www.textverified.com/docs/api/v2). Every path, field name
and state string below comes from that document. Nothing here is guessed.

How this adapter behaves:

* Official HTTPS API only. No scraping, no browser automation, no working
  around authentication, CAPTCHAs, rate limits or payment controls.
* A bearer token is obtained from the documented auth endpoint and cached
  until shortly before it expires, so we are not re-authenticating on every
  call.
* `create_order` prices the service first and sends `maxPrice`, so an upstream
  price move cannot quietly bill us more than the customer was quoted.
* `Idempotency-Key` is forwarded on creation, so a retry after a network
  timeout cannot reserve - and bill us for - two numbers.

**AUTHORISATION.** TextVerified's terms prohibit sharing numbers with third
parties. Reselling access, which is what this platform does, needs an explicit
reseller or partner arrangement with them. Having the API documented is not
the same as being permitted to resell, and production still refuses to sell
until an authorised provider is configured. See docs/PROVIDER_INTEGRATION.md.

**Testing without spending balance.** The API documents mock service names
(`test_success201`, `test_delayed_success201`, `test_pending201`,
`test_timeout201`, `test_insufficient_balance`, `test_no_numbers`) and fixed
mock ids (`mock_ver_success`, `mock_ver_pending`, ...). They return fixed test
data, create no real numbers and no billing events. `tests/test_textverified_live.py`
uses them and is skipped unless an API key is present.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache

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

#: Seconds before expiry at which the cached token is refreshed anyway.
TOKEN_REFRESH_MARGIN = 60


class _NotConfigured(ServiceUnavailable):
    code = "PROVIDER_NOT_CONFIGURED"
    message = "This provider is not available yet."


def _decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class TextVerifiedProvider(VerificationProvider):
    key = "textverified"
    display_name = "TextVerified"

    #: Set from the Provider row / agreement, not assumed.
    permits_code_display = True
    supports_webhooks = False

    # -- endpoints, from the published OpenAPI v2 specification -----------
    BASE_URL = "https://www.textverified.com"
    PATH_TOKEN = "/api/pub/v2/auth"
    PATH_SERVICES = "/api/pub/v2/services"
    PATH_COUNTRIES = ""  # the v2 verification API has no country list; see get_countries
    PATH_PRICING = "/api/pub/v2/pricing/verifications"
    PATH_AVAILABILITY = "/api/pub/v2/inventory/verifications"
    PATH_CREATE_ORDER = "/api/pub/v2/verifications"
    PATH_ORDER_STATUS = "/api/pub/v2/verifications/{id}"
    PATH_ORDER_CANCEL = "/api/pub/v2/verifications/{id}/cancel"
    #: Their mechanism for "this number did not work" - the state machine has a
    #: verificationRefunded state that follows a report.
    PATH_ORDER_REFUND = "/api/pub/v2/verifications/{id}/report"
    PATH_SMS = "/api/pub/v2/sms"
    PATH_ACCOUNT = "/api/pub/v2/account/me"

    #: Request shape used throughout: SMS verifications on mobile numbers.
    CAPABILITY = "sms"
    NUMBER_TYPE = "mobile"

    #: The documented `state` enum, mapped onto our own vocabulary. Anything
    #: unlisted is treated as PENDING rather than assumed finished.
    STATE_MAP: dict[str, ProviderOrderState] = {
        "verificationpending": ProviderOrderState.WAITING_FOR_CODE,
        "verificationcompleted": ProviderOrderState.CODE_RECEIVED,
        "verificationreused": ProviderOrderState.CODE_RECEIVED,
        "verificationreactivated": ProviderOrderState.WAITING_FOR_CODE,
        "verificationcanceled": ProviderOrderState.CANCELLED,
        "verificationrefunded": ProviderOrderState.CANCELLED,
        "verificationtimedout": ProviderOrderState.EXPIRED,
        "verificationreported": ProviderOrderState.FAILED,
    }

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PROVIDER_CREDENTIALS.get("textverified", {})
        self.api_key = credentials.get("api_key", "")
        self.api_username = credentials.get("api_username", "")
        self.base_url = (credentials.get("base_url") or self.BASE_URL).rstrip("/")
        self._session = requests.Session()
        self._token: str | None = None
        self._token_expires: datetime | None = None

    # -- plumbing --------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        # Both halves are required: the documented auth endpoint takes the
        # account email and the API key together.
        return bool(self.api_key and self.api_username and self.base_url)

    def _require_configured(self, what: str) -> None:
        if not self.is_configured:
            logger.error("provider_not_configured", extra={"operation": what})
            raise _NotConfigured()

    def _url(self, path: str, **kwargs) -> str:
        if not path:
            raise _NotConfigured()
        return f"{self.base_url}{path.format(**kwargs)}"

    @property
    def _token_cache_key(self) -> str:
        return f"textverified:token:{self.api_username}"

    def _bearer_token(self) -> str:
        """A valid bearer token, cached until shortly before it expires.

        Shared through the Django cache so the web, worker and beat processes
        do not each hold their own - re-authenticating on every call would be
        rude and would eat the rate limit for no reason.
        """
        now = datetime.now(UTC)
        if self._token and self._token_expires and self._token_expires > now:
            return self._token

        cached = cache.get(self._token_cache_key)
        if cached:
            token, expires_raw = cached
            expires = _parse_time(expires_raw)
            if token and expires and expires > now:
                self._token, self._token_expires = token, expires
                return token

        response = self._raw_request(
            "POST",
            self._url(self.PATH_TOKEN),
            headers={"X-API-USERNAME": self.api_username, "X-API-KEY": self.api_key},
        )
        token = str(response.get("token") or "")
        if not token:
            logger.error("textverified_auth_no_token")
            raise ProviderError("The verification provider did not return a session.")

        expires = _parse_time(response.get("expiresAt"))
        if expires is None:
            seconds = int(_decimal(response.get("expiresIn"), Decimal("300")))
            expires = now + timedelta(seconds=seconds)

        self._token, self._token_expires = token, expires
        ttl = max(int((expires - now).total_seconds()) - TOKEN_REFRESH_MARGIN, 30)
        cache.set(self._token_cache_key, (token, expires.isoformat()), ttl)
        logger.info("textverified_token_issued", extra={"expires_at": expires.isoformat()})
        return token

    def _raw_request(self, method: str, url: str, *, headers: dict | None = None,
                     json_body: dict | None = None, params: dict | None = None):
        """One HTTP call. Provider internals never reach the caller."""
        try:
            response = self._session.request(
                method, url, headers=headers or {}, json=json_body, params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.Timeout as exc:
            logger.warning("textverified_timeout", extra={"url_path": url[-60:]})
            raise ProviderError("The verification provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("textverified_transport_error", extra={"url_path": url[-60:]})
            raise ProviderError("We could not reach the verification provider.") from exc

        if response.status_code == 429:
            # Back off; never retry through a rate limit.
            logger.warning("textverified_rate_limited")
            raise ServiceUnavailable(
                "The verification provider is busy. Please try again shortly.",
                code="PROVIDER_RATE_LIMITED",
            )
        if response.status_code in (401, 403):
            logger.error("textverified_unauthorised", extra={"status": response.status_code})
            raise ProviderError("The verification provider rejected our credentials.")
        if response.status_code == 404:
            raise ProviderError("The verification provider does not recognise that request.")

        try:
            payload = response.json() if response.content else {}
        except ValueError as exc:
            logger.error("textverified_unreadable_response",
                         extra={"status": response.status_code})
            raise ProviderError(
                "The verification provider returned an unreadable response."
            ) from exc

        if response.status_code >= 400:
            # The documented error shape is {errorCode, errorDescription}.
            code = str(payload.get("errorCode", ""))[:60]
            logger.error("textverified_error", extra={"status": response.status_code,
                                                      "provider_code": code})
            raise ProviderError(_message_for(code))
        return payload

    def _request(self, method: str, url: str, *, json_body: dict | None = None,
                 params: dict | None = None, extra_headers: dict | None = None):
        self._require_configured(method + " " + url[-40:])
        headers = {"Authorization": f"Bearer {self._bearer_token()}",
                   "Accept": "application/json"}
        headers.update(extra_headers or {})
        return self._raw_request(method, url, headers=headers, json_body=json_body,
                                 params=params)

    def _map_state(self, raw_state: str, *, has_number: bool = False) -> ProviderOrderState:
        mapped = self.STATE_MAP.get(str(raw_state or "").lower())
        if mapped is None:
            # An unknown state must never read as finished: treat it as still
            # in flight and let the expiry sweep settle it.
            logger.warning("textverified_unknown_state", extra={"state": str(raw_state)[:40]})
            return ProviderOrderState.PENDING
        if mapped is ProviderOrderState.WAITING_FOR_CODE and not has_number:
            return ProviderOrderState.PENDING
        return mapped

    # -- catalog ---------------------------------------------------------

    def get_services(self) -> list[ProviderServiceDTO]:
        """Every service we can price.

        The service list and the price are separate documented calls, so this
        prices each service individually. A service we cannot price is left out
        rather than listed at a guessed cost - an unpriced row would be sold at
        the wrong price.
        """
        self._require_configured("listing services")
        payload = self._request(
            "GET", self._url(self.PATH_SERVICES),
            params={"numberType": self.NUMBER_TYPE, "reservationType": "verification"},
        )

        limit = int(settings.VERIFYGH.get("PROVIDER_CATALOG_LIMIT", 60))
        services: list[ProviderServiceDTO] = []
        skipped = 0
        for entry in payload if isinstance(payload, list) else []:
            name = str(entry.get("serviceName") or "").strip()
            if not name:
                continue
            if len(services) >= limit:
                skipped += 1
                continue
            try:
                cost = self.get_pricing(name, "US")
            except ProviderError:
                skipped += 1
                continue
            services.append(
                ProviderServiceDTO(
                    code=name,
                    name=str(entry.get("description") or name)[:120],
                    country_code="US",
                    cost=cost,
                    currency="USD",
                    supports_sms=True,
                    supports_voice=False,
                    ttl_minutes=int(settings.VERIFYGH["ORDER_TTL_MINUTES"]),
                )
            )

        logger.info("textverified_services_synced",
                    extra={"listed": len(services), "skipped": skipped})
        return services

    def get_countries(self) -> list[ProviderCountryDTO]:
        """TextVerified's v2 verification API sells US numbers.

        There is no country endpoint in the specification - only area codes
        within the US - so this reports exactly that rather than inventing a
        catalogue of countries we cannot actually source.
        """
        return [ProviderCountryDTO(code="US", name="United States", dial_code="+1")]

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        self._require_configured("pricing")
        payload = self._request(
            "POST", self._url(self.PATH_PRICING),
            json_body={
                "serviceName": service_code,
                "areaCode": False,
                "carrier": False,
                "numberType": self.NUMBER_TYPE,
                "capability": self.CAPABILITY,
            },
        )
        price = _decimal(payload.get("price"), Decimal("-1"))
        if price < 0:
            raise ProviderError("The verification provider did not return a price.")
        return price

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        self._require_configured("availability")
        payload = self._request(
            "POST", self._url(self.PATH_AVAILABILITY),
            json_body={
                "serviceName": service_code,
                "numberType": self.NUMBER_TYPE,
                "capability": self.CAPABILITY,
            },
        )
        quantity = payload.get("availableQuantity")
        count = int(quantity) if isinstance(quantity, int | float) else None
        return AvailabilityDTO(available=bool(count), count=count)

    # -- orders ----------------------------------------------------------

    def create_order(self, service_code: str, country_code: str,
                     idempotency_key: str) -> ProviderOrderDTO:
        """Reserve a number.

        The price is fetched first and sent as `maxPrice`, with a small
        tolerance: without it, an upstream price move between our quote and
        this call would be billed to us silently. If the provider's price has
        moved beyond the tolerance it answers PricingFailure and we fail the
        order, which refunds the customer.
        """
        self._require_configured("creating an order")
        price = self.get_pricing(service_code, country_code)
        tolerance = _decimal(
            settings.VERIFYGH.get("PROVIDER_PRICE_TOLERANCE", "1.05"), Decimal("1.05")
        )
        max_price = (price * tolerance).quantize(Decimal("0.01"))

        created = self._request(
            "POST", self._url(self.PATH_CREATE_ORDER),
            json_body={
                "serviceName": service_code,
                "capability": self.CAPABILITY,
                "maxPrice": float(max_price),
            },
            # Forwarded so a retry after a timeout cannot reserve two numbers.
            extra_headers={"Idempotency-Key": idempotency_key[:128]},
        )

        # The documented 201 response is a link to the new verification.
        href = str(created.get("href") or "")
        if not href:
            raise ProviderError("The verification provider did not return the reservation.")
        details = self._request("GET", href if href.startswith("http")
                                else f"{self.base_url}{href}")
        return self._order_from_details(details)

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        self._require_configured("order status")
        details = self._request(
            "GET", self._url(self.PATH_ORDER_STATUS, id=provider_order_id)
        )
        return self._order_from_details(details)

    def _order_from_details(self, details: dict) -> ProviderOrderDTO:
        number = str(details.get("number") or "")
        state = self._map_state(details.get("state"), has_number=bool(number))

        code = None
        if state is ProviderOrderState.CODE_RECEIVED:
            code = self._code_from_link(details)

        return ProviderOrderDTO(
            provider_order_id=str(details.get("id") or ""),
            state=state,
            phone_number=number,
            expires_at=_parse_time(details.get("endsAt")),
            cost=_decimal(details.get("totalCost"), Decimal("0")) or None,
            currency="USD",
            code=code,
            raw={"state": str(details.get("state") or ""),
                 "serviceName": str(details.get("serviceName") or "")},
        )

    def _code_from_link(self, details: dict) -> CodeDTO | None:
        """Follow the SMS link on a verification, as the docs' flow describes."""
        sms_link = (details.get("sms") or {}).get("href")
        verification_id = str(details.get("id") or "")
        if sms_link:
            url = sms_link if str(sms_link).startswith("http") else f"{self.base_url}{sms_link}"
            payload = self._request("GET", url)
        elif verification_id:
            payload = self._request("GET", self._url(self.PATH_SMS),
                                    params={"reservationId": verification_id})
        else:
            return None
        return self._first_code(payload)

    @staticmethod
    def _first_code(payload) -> CodeDTO | None:
        messages = payload.get("data") if isinstance(payload, dict) else None
        if not messages:
            return None
        message = messages[0]
        text = str(message.get("smsContent") or "")
        parsed = str(message.get("parsedCode") or "")
        if not parsed and not text:
            return None
        return CodeDTO(
            code=parsed,
            full_text=text,
            received_at=_parse_time(message.get("createdAt")),
            sender=str(message.get("from") or ""),
        )

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        self._require_configured("reading a code")
        payload = self._request("GET", self._url(self.PATH_SMS),
                                params={"reservationId": provider_order_id})
        return self._first_code(payload)

    def cancel_order(self, provider_order_id: str) -> bool:
        self._require_configured("cancelling an order")
        try:
            self._request("POST", self._url(self.PATH_ORDER_CANCEL, id=provider_order_id))
        except ProviderError:
            # A number that cannot be cancelled (already used, already gone) is
            # not an error the customer can act on.
            logger.info("textverified_cancel_refused", extra={"order": provider_order_id[:40]})
            return False
        return True

    #: `POST /verifications/{id}/report` is documented for issues "such as
    #: 'number already in use', 'verification failed', or 'code not received'".
    supports_issue_reports = True

    def refund_order(self, provider_order_id: str) -> bool:
        """Report a verification that did not work, which is their refund path."""
        self._require_configured("refunding an order")
        return self._report(provider_order_id)

    def report_number_issue(self, provider_order_id: str, reason: str) -> bool | None:
        """The same documented report call. It takes no body, so `reason` stays ours.

        It returns 400 when "the verification does not allow reporting" - after
        their own window, for instance - which comes back here as False.
        """
        self._require_configured("reporting a number")
        return self._report(provider_order_id)

    def _report(self, provider_order_id: str) -> bool:
        try:
            self._request("POST", self._url(self.PATH_ORDER_REFUND, id=provider_order_id))
        except ProviderError:
            logger.info("textverified_report_refused", extra={"order": provider_order_id[:40]})
            return False
        return True

    # -- health ----------------------------------------------------------

    def health_check(self) -> bool:
        if not self.is_configured:
            return False
        try:
            self._request("GET", self._url(self.PATH_ACCOUNT))
            return True
        except Exception:
            return False

    def account_balance(self) -> Decimal | None:
        """Our balance with the provider. Surfaced on the admin health page so
        nobody discovers an empty upstream account through failed orders."""
        if not self.is_configured:
            return None
        try:
            payload = self._request("GET", self._url(self.PATH_ACCOUNT))
        except Exception:
            return None
        return _decimal(payload.get("currentBalance"), Decimal("0"))


#: Documented create-error codes, translated into something a customer can read.
_ERROR_MESSAGES = {
    "insufficientbalance": "Numbers are temporarily unavailable. Please try again later.",
    "unavailable": "No number is available for that service right now.",
    "pricingfailure": "That service's price has changed. Please try again.",
    "toomanyunfinishedverifications": "Please finish your active order first.",
}


def _message_for(provider_code: str) -> str:
    return _ERROR_MESSAGES.get(
        provider_code.lower().replace(" ", ""),
        "The verification provider could not complete that request.",
    )
