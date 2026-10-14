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

* `v2.sms.received` webhooks are verified (HMAC-SHA512 over the raw body,
  `X-Webhook-Signature`) and used only as a prompt to read the order back
  through the API. Polling stays the source of truth.

**AUTHORISATION.** TextVerified's terms (read 2026-09-29) say sharing its numbers
with third parties is prohibited, and its FAQ says it is not a reseller. Selling
its numbers to our customers therefore needs its written permission. Until
staff record that permission on the provider row (`resale_authorized`), this
adapter may sync the catalogue, read prices and read our balance, but nothing
is listed to customers or ordered for them. See docs/PROVIDERS.md.

**Testing without spending balance.** The API documents mock service names
(`test_success201`, `test_delayed_success201`, `test_pending201`,
`test_timeout201`, `test_insufficient_balance`, `test_no_numbers`) and fixed
mock ids (`mock_ver_success`, `mock_ver_pending`, ...). They return fixed test
data, create no real numbers and no billing events. `tests/test_textverified_live.py`
uses them and is skipped unless an API key is present.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache

from apps.common.errors import ProviderError, ServiceUnavailable
from apps.verification import pacing
from apps.verification.base import (
    AvailabilityDTO,
    BalanceDTO,
    CodeDTO,
    ProviderCountryDTO,
    ProviderOrderDTO,
    ProviderOrderState,
    ProviderServiceDTO,
    RentalDTO,
    RentalExtensionDTO,
    RentalMessageDTO,
    RentalState,
    VerificationProvider,
)

logger = logging.getLogger("verifygh.provider.textverified")

REQUEST_TIMEOUT = 20

#: Seconds before expiry at which the cached token is refreshed anyway.
TOKEN_REFRESH_MARGIN = 60

#: How long one catalogue sync may spend pricing services by default. Each
#: price is its own documented call, and the sync runs inside a Celery task
#: with a time limit, so it prices what it can in this window and resumes next
#: time. Callers inside a web request pass a shorter budget.
SYNC_TIME_BUDGET_SECONDS = 60

#: At most this many priority services are priced ahead of the rotation.
PRIORITY_LIMIT = 60

#: Where the next catalogue sync resumes pricing.
PRICING_CURSOR_KEY = "textverified:pricing_cursor"

#: Documented error codes that mean "our account", not "this customer" - an
#: empty balance stops every order and needs a person to top it up.
OPERATIONAL_ERROR_CODES = {"insufficientbalance"}

#: A purchase TextVerified answers "Unavailable" reserved nothing, and the
#: shortage is often momentary (the same number can be bought minutes later).
#: One more try after this pause, before the customer is refunded.
UNAVAILABLE_RETRY_SECONDS = 3

#: Rental lengths as the documented `RentalDuration` enum names them, by days.
RENTAL_DURATIONS = {
    1: "oneDay", 3: "threeDay", 7: "sevenDay", 14: "fourteenDay",
    30: "thirtyDay", 90: "ninetyDay", 365: "oneYear",
}

#: The documented non-renewable rental states (`ReservationState`).
RENTAL_STATE_MAP = {
    "nonrenewableactive": RentalState.ACTIVE,
    "nonrenewableexpired": RentalState.EXPIRED,
    "nonrenewablerefunded": RentalState.REFUNDED,
}

#: Pages of a rental's SMS list read in one go. Newest first, so the cap only
#: ever leaves out the oldest messages of a very busy number.
RENTAL_SMS_MAX_PAGES = 5

WEBHOOK_SIGNATURE_HEADER = "x-webhook-signature"
WEBHOOK_SIGNATURE_PREFIX = "HMAC-SHA512="


class _NotConfigured(ServiceUnavailable):
    code = "PROVIDER_NOT_CONFIGURED"
    message = "This provider is not available yet."


def _provider_error(message: str, provider_code: str = "", *,
                    operational: bool = False) -> ProviderError:
    """A ProviderError carrying TextVerified's own code for staff alerting.

    The message is what a customer could ever see; the code stays internal.
    """
    error = ProviderError(message)
    error.provider_code = provider_code
    error.operational = operational
    return error


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
    #: Documented: signed `v2.sms.received` callbacks. Acted on only when the
    #: webhook secret is configured (see `accepts_webhooks`).
    supports_webhooks = True
    #: `GET /api/pub/v2/account/me` reports `currentBalance`.
    supports_balance = True

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
    #: "Reuse Verification": another code on the same number, only shortly
    #: after a verification completes (the details' `reuse.reusableUntil`).
    PATH_ORDER_REUSE = "/api/pub/v2/verifications/{id}/reuse"
    #: "Reactivate a completed verification that can no longer be reused";
    #: eligibility is the verification's `reactivate.canReactivate`.
    PATH_ORDER_REACTIVATE = "/api/pub/v2/verifications/{id}/reactivate"
    #: Their mechanism for "this number did not work" - the state machine has a
    #: verificationRefunded state that follows a report.
    PATH_ORDER_REFUND = "/api/pub/v2/verifications/{id}/report"
    PATH_SMS = "/api/pub/v2/sms"
    PATH_ACCOUNT = "/api/pub/v2/account/me"
    # Rentals: non-renewable only - a fixed period, prepaid, extendable.
    PATH_RENTAL_PRICING = "/api/pub/v2/pricing/rentals"
    PATH_RENTAL_INVENTORY = "/api/pub/v2/inventory/rentals"
    PATH_RENTAL_CREATE = "/api/pub/v2/reservations/rental"
    PATH_RENTAL = "/api/pub/v2/reservations/rental/nonrenewable/{id}"
    PATH_RENTAL_REFUND = "/api/pub/v2/reservations/rental/nonrenewable/{id}/refund"
    PATH_RENTAL_EXTEND = "/api/pub/v2/reservations/rentals/extensions"
    PATH_SALE = "/api/pub/v2/sales/{id}"

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
        self.webhook_secret = str(credentials.get("webhook_secret") or "")
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
            # Back off; never retry through a rate limit. The docs say limits
            # may change, so the caller (the next beat tick, the customer's
            # retry) is the backoff.
            logger.warning("textverified_rate_limited")
            # Background work (sync, stock rechecks) stands aside for customers.
            pacing.note_throttled(self.key)
            busy = ServiceUnavailable(
                "The verification provider is busy. Please try again shortly.",
                code="PROVIDER_RATE_LIMITED",
            )
            busy.provider_code = "RATE_LIMITED"
            raise busy
        if response.status_code in (401, 403):
            logger.error("textverified_unauthorised", extra={"status": response.status_code})
            refused = _provider_error("The verification provider rejected our credentials.",
                                      "UNAUTHORIZED", operational=True)
            refused.http_status = response.status_code
            raise refused
        if response.status_code == 404:
            missing = ProviderError("The verification provider does not recognise that request.")
            missing.http_status = 404
            raise missing

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
            code = str(payload.get("errorCode", "") if isinstance(payload, dict) else "")[:60]
            operational = code.lower() in OPERATIONAL_ERROR_CODES
            # TextVerified's own explanation, for staff: it says *why* ("price
            # above maxPrice", "no stock for these options") where the code
            # alone cannot. Long digit runs are masked - a description must
            # never put a number or a code in the log.
            description = str(payload.get("errorDescription", "")
                              if isinstance(payload, dict) else "")
            description = re.sub(r"\d{4,}", "#", description)[:200]
            logger.error("textverified_error", extra={"status": response.status_code,
                                                      "provider_code": code,
                                                      "provider_description": description,
                                                      "operational": operational})
            error = _provider_error(_message_for(code), code, operational=operational)
            error.http_status = response.status_code
            raise error
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

    def get_services(self, *, priority: list[str] | None = None,
                     time_budget: float | None = None,
                     skip: set[str] | None = None) -> list[ProviderServiceDTO]:
        """Every service we can price, a slice per sync.

        The service list is one documented call; each price is another
        (`POST /pricing/verifications`, 2,300+ services), and the docs warn
        pricing may answer 429. So one sync:

        * prices the `priority` services first (the ones customers actually
          buy - the full list is alphabetical, so "009ibbq" would otherwise
          come long before TikTok);
        * then continues through the rest from where the last sync stopped;
        * stops at PROVIDER_CATALOG_LIMIT services (0 = no count limit) or
          when `time_budget` seconds are spent;
        * skips services in `skip` (lowercased names priced recently): their
          price stands, and the call is saved for one that needs it;
        * paces its calls through apps/verification/pacing.py: an interval
          learned across runs, doubled after a 429 and eased after successes,
          and a pause whenever any call - a customer's included - was just
          throttled, so the sync never bursts into the rate limit.

        Services not priced this time are not returned, so the catalogue keeps
        their last known price instead of dropping them. A service that cannot
        be priced is left out rather than listed at a guessed cost. Voice-only
        services are skipped: we sell SMS verifications.
        """
        self._require_configured("listing services")
        payload = self._request(
            "GET", self._url(self.PATH_SERVICES),
            params={"numberType": self.NUMBER_TYPE, "reservationType": "verification"},
        )

        entries: list[tuple[str, str]] = []
        for entry in payload if isinstance(payload, list) else []:
            name = str(entry.get("serviceName") or "").strip()
            if not name or str(entry.get("capability") or "").lower() == "voice":
                continue
            entries.append((name, str(entry.get("description") or name)[:120]))
        if not entries:
            return []

        # Priority first, in the caller's order; then the rest, rotated.
        by_name = {name.lower(): (name, description) for name, description in entries}
        first: list[tuple[str, str]] = []
        for code in priority or []:
            match = by_name.get(str(code).lower())
            if match and match not in first:
                first.append(match)
            if len(first) >= PRIORITY_LIMIT:
                break
        fresh = {code.lower() for code in skip or ()}
        skipped_fresh = sum(1 for name, _ in entries if name.lower() in fresh)
        first = [entry for entry in first if entry[0].lower() not in fresh]
        chosen = set(first)
        rest = [entry for entry in entries
                if entry not in chosen and entry[0].lower() not in fresh]
        start = int(cache.get(PRICING_CURSOR_KEY) or 0) % len(rest) if rest else 0
        queue = first + rest[start:] + rest[:start]

        limit = int(settings.VERIFYGH.get("PROVIDER_CATALOG_LIMIT", 60))
        budget = len(queue) if limit <= 0 else min(limit, len(queue))
        seconds = SYNC_TIME_BUDGET_SECONDS if time_budget is None else max(0.0, time_budget)
        deadline = time.monotonic() + seconds

        services: list[ProviderServiceDTO] = []
        skipped = attempted = rate_limited = 0
        stopped = ""
        while attempted < budget:
            # Paced, and aside while anyone is being throttled: a 429 below
            # doubles the interval and starts a pause, so it is waited out
            # here rather than retried into.
            if not pacing.wait_turn(self.key, deadline, clock=time.monotonic,
                                    sleep=time.sleep):
                stopped = "time_budget"
                break
            name, description = queue[attempted]
            try:
                cost = self.get_pricing(name, "US")
            except ServiceUnavailable:
                rate_limited += 1
                continue
            except ProviderError:
                attempted += 1
                skipped += 1
                continue
            pacing.note_ok(self.key)
            attempted += 1
            services.append(
                ProviderServiceDTO(
                    code=name,
                    name=description,
                    country_code="US",
                    cost=cost,
                    currency="USD",
                    supports_sms=True,
                    supports_voice=False,
                    ttl_minutes=int(settings.VERIFYGH["ORDER_TTL_MINUTES"]),
                    reports_stock=False,
                )
            )

        # The cursor moves over the rotated part only; priority services are
        # priced first on every sync.
        rotated = max(0, attempted - len(first))
        if rest:
            cache.set(PRICING_CURSOR_KEY, (start + rotated) % len(rest), None)
        logger.info("textverified_services_synced", extra={
            "listed": len(services), "skipped": skipped, "fresh": skipped_fresh,
            "catalogue": len(entries), "interval": round(pacing.interval(self.key), 2),
            "priority": len(first), "rate_limited": rate_limited,
            "stopped": stopped or "complete",
        })
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
        # Rounded up: rounding to the nearest cent could cut the tolerance to
        # nothing on a cheap service ($0.10 x 1.05 would round back to $0.10).
        max_price = (price * tolerance).quantize(Decimal("0.01"), rounding=ROUND_CEILING)

        body = {
            "serviceName": service_code,
            "capability": self.CAPABILITY,
            "maxPrice": float(max_price),
        }
        for attempt in (1, 2):
            # Forwarded so a retry after a timeout cannot reserve two numbers.
            # The second attempt needs a key of its own: the first answered
            # 400 and reserved nothing, and its key would replay that answer.
            key = idempotency_key if attempt == 1 else f"{idempotency_key}:retry"
            try:
                created = self._request(
                    "POST", self._url(self.PATH_CREATE_ORDER),
                    json_body=body, extra_headers={"Idempotency-Key": key[:128]},
                )
                break
            except ProviderError as exc:
                code = str(getattr(exc, "provider_code", "") or "")
                logger.warning("textverified_create_refused", extra={
                    "service": service_code[:60], "attempt": attempt, "provider_code": code,
                    "price": str(price), "max_price": str(max_price),
                })
                if attempt == 2 or code.lower() != "unavailable":
                    raise
                time.sleep(UNAVAILABLE_RETRY_SECONDS)

        # The documented 201 response is a link to the new verification.
        href = str(created.get("href") or "")
        if not href:
            raise ProviderError("The verification provider did not return the reservation.")
        details = self._request("GET", href if href.startswith("http")
                                else f"{self.base_url}{href}")
        return self._order_from_details(details)

    supports_reuse = True

    def reuse_order(self, provider_order_id: str, idempotency_key: str) -> ProviderOrderDTO:
        """`POST /verifications/{id}/reuse`, then read the new verification.

        The docs give reuse no Idempotency-Key and no price in advance: a new
        verification is created and its `totalCost` says what it cost. A 400
        means the verification is no longer eligible (the window closed).
        """
        self._require_configured("reusing a number")
        created = self._request("POST", self._url(self.PATH_ORDER_REUSE, id=provider_order_id))
        href = str(created.get("href") or "")
        if not href:
            raise _provider_error("The verification provider did not return the reuse.")
        details = self._request("GET", href if href.startswith("http")
                                else f"{self.base_url}{href}")
        return self._order_from_details(details)

    supports_reactivation = True

    def can_reactivate(self, provider_order_id: str) -> bool:
        """The verification's own `reactivate.canReactivate`, read live."""
        self._require_configured("checking reactivation")
        details = self._request("GET", self._url(self.PATH_ORDER_STATUS, id=provider_order_id))
        return bool((details.get("reactivate") or {}).get("canReactivate"))

    def reactivate_order(self, provider_order_id: str,
                         idempotency_key: str) -> ProviderOrderDTO:
        """`POST /verifications/{id}/reactivate`, then read the verification it links to.

        Like reuse, the docs give it no Idempotency-Key and no price in advance
        (only rentals have a reactivation price): the new verification's
        `totalCost` says what it cost. A 400 means it is not eligible.
        """
        self._require_configured("reactivating a number")
        created = self._request("POST", self._url(self.PATH_ORDER_REACTIVATE,
                                                  id=provider_order_id))
        href = str(created.get("href") or "")
        if not href:
            raise _provider_error("The verification provider did not return the reactivation.")
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
        number = _e164(details.get("number"))
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
            reusable_until=_parse_time((details.get("reuse") or {}).get("reusableUntil")),
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
        parsed = _clean_code(message.get("parsedCode"))
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

    #: A report moves the verification to `verificationReported`, and a refund
    #: to `verificationRefunded` - both in the documented state enum.
    tracks_report_refunds = True

    def report_outcome(self, provider_order_id: str) -> str | None:
        self._require_configured("checking a report")
        state = str(self.get_order_status(provider_order_id).raw.get("state", "")).lower()
        return "REFUNDED" if state == "verificationrefunded" else "PENDING"

    def _report(self, provider_order_id: str) -> bool:
        try:
            self._request("POST", self._url(self.PATH_ORDER_REFUND, id=provider_order_id))
        except ProviderError:
            logger.info("textverified_report_refused", extra={"order": provider_order_id[:40]})
            return False
        return True

    # -- rentals -----------------------------------------------------------

    #: Documented: non-renewable rentals, bought for a fixed period from our
    #: balance, refundable while the rental's own `refund.canRefund` says so,
    #: and extendable (extensions are not refundable).
    supports_rentals = True

    @staticmethod
    def _rental_duration(days: int) -> str:
        try:
            return RENTAL_DURATIONS[int(days)]
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Unsupported rental length: {days!r} days") from None

    def _follow(self, link) -> dict:
        href = str(link.get("href") or "") if isinstance(link, dict) else ""
        if not href:
            raise _provider_error("The verification provider did not return a link.")
        return self._request("GET", href if href.startswith("http") else f"{self.base_url}{href}")

    def rental_price(self, service_code: str, days: int) -> Decimal | None:
        """`POST /pricing/rentals`. None for a combination they do not sell (400)."""
        self._require_configured("rental pricing")
        try:
            payload = self._request("POST", self._url(self.PATH_RENTAL_PRICING), json_body={
                "serviceName": service_code,
                "areaCode": False,
                "numberType": self.NUMBER_TYPE,
                "capability": self.CAPABILITY,
                "isRenewable": False,
                "duration": self._rental_duration(days),
            })
        except ProviderError as exc:
            if getattr(exc, "http_status", None) == 400:
                return None
            raise
        price = _decimal(payload.get("price") if isinstance(payload, dict) else None,
                         Decimal("-1"))
        if price <= 0:
            raise _provider_error("The verification provider did not return a price.")
        return price

    def rental_stock(self, service_code: str, days: int) -> int:
        """`POST /inventory/rentals` -> `availableQuantity` (capped at 9000 by them)."""
        self._require_configured("rental inventory")
        try:
            payload = self._request("POST", self._url(self.PATH_RENTAL_INVENTORY), json_body={
                "serviceName": service_code,
                "numberType": self.NUMBER_TYPE,
                "capability": self.CAPABILITY,
                "duration": self._rental_duration(days),
            })
        except ProviderError as exc:
            if getattr(exc, "http_status", None) == 400:
                return 0
            raise
        quantity = payload.get("availableQuantity") if isinstance(payload, dict) else None
        return int(quantity) if isinstance(quantity, int | float) and quantity > 0 else 0

    def create_rental(self, service_code: str, days: int, idempotency_key: str) -> RentalDTO:
        """`POST /reservations/rental`, then the sale it links to, then the rental.

        The documented flow. `Idempotency-Key` makes a retry after a timeout
        safe: a completed purchase answers with the same sale; one still
        running answers 409 IdempotencyConflict (raised, for the caller to try
        again later). No back orders: a rental out of stock is refused, not
        queued.
        """
        self._require_configured("renting a number")
        created = self._request(
            "POST", self._url(self.PATH_RENTAL_CREATE),
            json_body={
                "allowBackOrderReservations": False,
                "isRenewable": False,
                "duration": self._rental_duration(days),
                "numberType": self.NUMBER_TYPE,
                "serviceName": service_code,
                "capability": self.CAPABILITY,
            },
            extra_headers={"Idempotency-Key": idempotency_key[:256]},
        )
        return self._rental_from_sale(self._follow(created))

    def get_rental_sale(self, sale_id: str) -> RentalDTO:
        self._require_configured("reading a rental purchase")
        return self._rental_from_sale(self._request("GET", self._url(self.PATH_SALE, id=sale_id)))

    def _rental_from_sale(self, sale: dict) -> RentalDTO:
        sale = sale if isinstance(sale, dict) else {}
        sale_id = str(sale.get("id") or "")
        state = str(sale.get("state") or "").lower()
        cost = _decimal(sale.get("total"), Decimal("0")) or None
        if state == "failed":
            return RentalDTO(state=RentalState.FAILED, sale_id=sale_id, cost=cost)
        rental = next((item for item in sale.get("reservations") or []
                       if isinstance(item, dict)
                       and str(item.get("reservationType") or "").lower() == "nonrenewable"),
                      None)
        if rental is None:
            # created / processing: nothing to read yet.
            return RentalDTO(state=RentalState.PENDING, sale_id=sale_id, cost=cost)
        dto = self._rental_from_details(self._follow(rental.get("link")))
        return dataclasses.replace(dto, sale_id=sale_id or dto.sale_id, cost=cost)

    def get_rental(self, provider_rental_id: str) -> RentalDTO:
        self._require_configured("reading a rental")
        return self._rental_from_details(
            self._request("GET", self._url(self.PATH_RENTAL, id=provider_rental_id)))

    def _rental_from_details(self, details: dict) -> RentalDTO:
        details = details if isinstance(details, dict) else {}
        raw_state = str(details.get("state") or "")
        state = RENTAL_STATE_MAP.get(raw_state.lower())
        if state is None:
            logger.warning("textverified_unknown_rental_state", extra={"state": raw_state[:40]})
            state = RentalState.UNKNOWN
        refund = details.get("refund") if isinstance(details.get("refund"), dict) else {}
        return RentalDTO(
            state=state,
            provider_rental_id=str(details.get("id") or "")[:128],
            sale_id=str(details.get("saleId") or "")[:128],
            phone_number=_e164(details.get("number")),
            ends_at=_parse_time(details.get("endsAt")),
            can_refund=bool(refund.get("canRefund")),
            refundable_until=_parse_time(refund.get("refundableUntil")),
        )

    def refund_rental(self, provider_rental_id: str) -> bool:
        """`POST /reservations/rental/nonrenewable/{id}/refund`: 400 when not refundable."""
        self._require_configured("refunding a rental")
        try:
            self._request("POST", self._url(self.PATH_RENTAL_REFUND, id=provider_rental_id))
        except ProviderError as exc:
            if 400 <= int(getattr(exc, "http_status", 0) or 0) < 500:
                logger.info("textverified_rental_refund_refused",
                            extra={"rental": provider_rental_id[:40]})
                return False
            raise
        return True

    def extend_rental(self, provider_rental_id: str, days: int) -> RentalExtensionDTO:
        """`POST /reservations/rentals/extensions`. Not refundable upstream."""
        self._require_configured("extending a rental")
        payload = self._request("POST", self._url(self.PATH_RENTAL_EXTEND), json_body={
            "rentalId": provider_rental_id,
            "extensionDuration": self._rental_duration(days),
        })
        payload = payload if isinstance(payload, dict) else {}
        return RentalExtensionDTO(
            provider_extension_id=str(payload.get("id") or "")[:128],
            new_ends_at=_parse_time(payload.get("newEndsAt")),
            cost=_decimal(payload.get("cost"), Decimal("0")) or None,
        )

    def rental_messages(self, provider_rental_id: str) -> list[RentalMessageDTO]:
        """`GET /sms?reservationId=`, following `links.next` a few pages."""
        self._require_configured("reading rental messages")
        payload = self._request("GET", self._url(self.PATH_SMS),
                                params={"reservationId": provider_rental_id})
        messages: list[RentalMessageDTO] = []
        for _ in range(RENTAL_SMS_MAX_PAGES):
            if not isinstance(payload, dict):
                break
            for item in payload.get("data") or []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                messages.append(RentalMessageDTO(
                    provider_message_id=str(item.get("id"))[:128],
                    body=str(item.get("smsContent") or "")[:2000],
                    code=_clean_code(item.get("parsedCode")) or "",
                    sender=str(item.get("from") or "")[:64],
                    received_at=_parse_time(item.get("createdAt")),
                ))
            following = (payload.get("links") or {}).get("next")
            if not payload.get("hasNext") or not isinstance(following, dict) \
                    or not following.get("href"):
                break
            payload = self._follow(following)
        return messages

    # -- our account -----------------------------------------------------

    def get_balance(self) -> BalanceDTO:
        """`GET /api/pub/v2/account/me` -> `currentBalance`.

        Read-only. TextVerified is funded with prepaid credits bought by card or
        cryptocurrency on its website; no API adds money. The Account schema has
        no held or frozen amount, and the FAQ says credits are deducted only
        when a verification comes in, so nothing is reported as frozen.
        """
        self._require_configured("reading the balance")
        payload = self._request("GET", self._url(self.PATH_ACCOUNT))
        if not isinstance(payload, dict) or payload.get("currentBalance") is None:
            raise _provider_error("The verification provider did not report a balance.")
        return BalanceDTO(available=_decimal(payload.get("currentBalance")),
                          frozen=Decimal("0"), currency="USD")

    # -- webhooks ----------------------------------------------------------

    @property
    def accepts_webhooks(self) -> bool:
        return bool(self.webhook_secret)

    def _signatures(self, raw_body: bytes) -> list[str]:
        """The documented signature: Base64(HMAC-SHA512(secret, body)).

        The docs name the secret (`whsec_...`) but not whether it is used as
        written or with its encoded part decoded, so both are computed. Either
        is derived from our secret alone, so accepting both admits nothing
        that does not hold it.
        """
        keys = [self.webhook_secret.encode()]
        if self.webhook_secret.startswith("whsec_"):
            try:
                keys.append(base64.b64decode(self.webhook_secret[6:], validate=True))
            except (binascii.Error, ValueError):
                pass
        return [base64.b64encode(hmac.new(key, raw_body, hashlib.sha512).digest()).decode()
                for key in keys]

    def parse_webhook(self, raw_body: bytes, headers: dict) -> list[str] | None:
        if not self.webhook_secret:
            return None
        header = str(headers.get(WEBHOOK_SIGNATURE_HEADER) or "").strip()
        if not header.startswith(WEBHOOK_SIGNATURE_PREFIX):
            return None
        given = header[len(WEBHOOK_SIGNATURE_PREFIX):].strip()
        if not any(hmac.compare_digest(given, expected)
                   for expected in self._signatures(raw_body)):
            return None
        try:
            event = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError):
            return []
        if not isinstance(event, dict):
            return []
        name = str(event.get("event") or event.get("Event") or "")
        data = event.get("data") or event.get("Data") or {}
        if name != "v2.sms.received" or not isinstance(data, dict):
            return []
        reservation = str(data.get("reservationId") or data.get("ReservationId") or "")
        return [reservation[:128]] if reservation else []

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
        """Our spendable balance with the provider, or None when it cannot be read."""
        if not self.is_configured:
            return None
        try:
            return self.get_balance().available
        except Exception:
            return None


def _e164(value) -> str:
    """TextVerified numbers are US numbers, returned as 10 bare digits.

    Stored in full international form (+1...), like every other provider's, so
    the number means the same thing everywhere it is shown, copied or matched.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def _clean_code(value) -> str:
    """A code the customer can paste as it is.

    TextVerified's `parsedCode` keeps the SMS's own spacing ("708 609 "); a
    6-digit field rejects or truncates that. A code of digits with spaces or
    dashes between them becomes the bare digits; anything else (such as
    Google's "G-123456") keeps its characters and loses only surrounding space.
    """
    text = str(value or "").strip()
    if re.fullmatch(r"\d[\d\s-]*\d", text):
        return re.sub(r"\D", "", text)
    return text


#: Documented create-error codes, translated into something a customer can read.
_ERROR_MESSAGES = {
    "insufficientbalance": "Numbers are temporarily unavailable. Please try again later.",
    "unavailable": "No number is available for that service right now.",
    "pricingfailure": "That service's price has changed. Please try again.",
    # Counts every number our account holds, not one customer's: never "your".
    "toomanyunfinishedverifications": "We are handling a lot of orders right now. "
                                      "Please try again in a minute.",
}


def _message_for(provider_code: str) -> str:
    return _ERROR_MESSAGES.get(
        provider_code.lower().replace(" ", ""),
        "The verification provider could not complete that request.",
    )
