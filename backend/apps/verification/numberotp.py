"""NumberOTP adapter: one-time US verification numbers.

Built 23 Nov 2026 from NumberOTP's published OpenAPI 3.1 file
(https://www.numberotp.com/openapi.yaml, "NumberOTP API" 1.0.0) and nothing
else. Base URL https://api.numberotp.com/v1; Bearer API key (`notp_...`).

    GET  /public/services?country=   {data: {services: [{code, name}]}}
    GET  /public/prices?country=     {data: {countryId: {code: {cost, count, pool}}}}
    POST /activations                {service, country, pool, max_price} +
                                     Idempotency-Key -> {data: {id, phoneNumber,
                                     expiresAt}}; 402 insufficient balance,
                                     404 not available here
    GET  /activations/{id}           {data: ActivationData} - status waiting |
                                     received | finished | canceled | expired,
                                     otp, full_sms, expires_at
    POST /activations/{id}/cancel    refunds a number with no SMS; 409 otherwise
    GET  /me                         {data: {balance, on_hold, currency}}

Identifiers are NumberOTP's own: service codes like `wa`, and numeric country
IDs - "187" is the United States (documented). Only the US is mapped: it is
the only country VerifyGH sells.

**Idempotent purchases.** The documented Idempotency-Key is forwarded, so a
retry after a timeout returns the first number instead of buying a second.

**Never above the listed price.** `max_price` is the price the catalogue
listed, so a dearer pool is skipped rather than charged.

**A code is proven by `otp`, never by a status name.**

**AUTHORISATION.** NumberOTP's published Reseller Agreement (numberotp.com/
reseller-agreement, updated 18 Jul 2026) grants a "right to purchase Service
capacity at wholesale pricing and resell it to Reseller's own end customers",
after applying on its Reseller Program page. Staff record that in Admin >
Providers (`resale_authorized`) before anything is sold through it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache

from apps.common.errors import ProviderError, ServiceUnavailable
from apps.verification.base import (
    AvailabilityDTO,
    BalanceDTO,
    CodeDTO,
    ProviderCountryDTO,
    ProviderOrderDTO,
    ProviderOrderState,
    ProviderServiceDTO,
    VerificationProvider,
)

logger = logging.getLogger("verifygh.provider.numberotp")

REQUEST_TIMEOUT = 20
CATALOGUE_CACHE_SECONDS = 6 * 3600

# shortcut: US only (the ID the docs give); add more from /public/countries if we sell more.
COUNTRY_IDS = {"US": "187"}

#: NumberOTP names that bundle several apps, mapped to our service slug.
ALIASES = {
    "instagramthreads": "instagram",
    "twitterx": "twitter",
    "tiktokdouyin": "tiktok",
    "googleyoutubegmail": "google",
}

_STATES = {
    "waiting": ProviderOrderState.WAITING_FOR_CODE,
    "canceled": ProviderOrderState.CANCELLED,
    "expired": ProviderOrderState.EXPIRED,
}


def slug_for(name: str) -> str:
    """'Twitter/X' -> 'twitter'; 'LinkedIN' -> 'linkedin'."""
    plain = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    return ALIASES.get(plain, plain)


def _decimal(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _e164(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}" if digits else ""


class NumberOTPProvider(VerificationProvider):
    key = "numberotp"
    display_name = "NumberOTP"
    permits_code_display = True
    supports_webhooks = False

    BASE_URL = "https://api.numberotp.com/v1"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PROVIDER_CREDENTIALS.get(self.key, {})
        self.api_key = str(self.config.get("api_key") or credentials.get("api_key") or "")
        self.base_url = str(credentials.get("base_url") or self.BASE_URL).rstrip("/")
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    # -- transport -------------------------------------------------------

    def _call(self, method: str, path: str, *, json: dict | None = None,
              params: dict | None = None, keyed: bool = True,
              idempotency_key: str = "") -> tuple[int, dict]:
        headers = {"Accept": "application/json"}
        if keyed:
            if not self.is_configured:
                logger.error("provider_not_configured", extra={"operation": path})
                raise ServiceUnavailable("Verification is temporarily unavailable.",
                                         code="PROVIDER_NOT_CONFIGURED")
            headers["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:255]
        try:
            response = self._session.request(method, f"{self.base_url}{path}", json=json,
                                             params=params, headers=headers,
                                             timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            logger.warning("numberotp_timeout", extra={"path": path})
            raise ProviderError("The verification provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("numberotp_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the verification provider.") from exc

        if response.status_code == 429:
            logger.warning("numberotp_rate_limited", extra={"path": path})
            raise ServiceUnavailable("The verification provider is busy. Please try again shortly.",
                                     code="PROVIDER_RATE_LIMITED")
        if response.status_code in (401, 403):
            logger.error("numberotp_unauthorised", extra={"path": path,
                                                          "status": response.status_code})
            raise ProviderError("The verification provider rejected our credentials.")
        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("numberotp_unreadable_response", extra={"path": path,
                                                                 "status": response.status_code})
            raise ProviderError(
                "The verification provider returned an unreadable response.") from exc
        if response.status_code >= 500 or not isinstance(payload, dict):
            logger.error("numberotp_http_error", extra={"path": path,
                                                        "status": response.status_code})
            raise ProviderError("The verification provider could not complete that request.")
        return response.status_code, payload

    @staticmethod
    def _data(payload: dict) -> dict:
        return payload.get("data") if isinstance(payload.get("data"), dict) else {}

    # -- catalogue -------------------------------------------------------

    def _country_id(self, country_code: str) -> str:
        country_id = COUNTRY_IDS.get(str(country_code).upper())
        if country_id is None:
            raise ProviderError("We do not offer numbers for that country.")
        return country_id

    def _catalogue(self, country_id: str) -> dict[str, dict]:
        """Our slug -> {code, cost, count}: the priced NumberOTP service for it.

        Where two NumberOTP services reduce to one slug ('Instagram+Threads'
        and 'Instagram'), the one with more numbers wins.
        """
        key = f"numberotp:catalogue:{country_id}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        _, services = self._call("GET", "/public/services", params={"country": country_id},
                                 keyed=False)
        _, prices = self._call("GET", "/public/prices", params={"country": country_id},
                               keyed=False)
        priced = self._data(prices).get(country_id) or {}
        catalogue: dict[str, dict] = {}
        for entry in self._data(services).get("services") or []:
            code = str(entry.get("code") or "")
            price = priced.get(code) if isinstance(priced.get(code), dict) else None
            cost = _decimal(price.get("cost")) if price else None
            if not code or cost is None:
                continue
            count = int(price.get("count") or 0)
            slug = slug_for(entry.get("name"))
            if slug and (slug not in catalogue or count > catalogue[slug]["count"]):
                catalogue[slug] = {"code": code, "cost": cost, "count": count}
        # Prices are cached upstream ~5 minutes; ours just avoids re-reading per order.
        cache.set(key, catalogue, 300)
        return catalogue

    def _entry(self, service_code: str, country_code: str) -> tuple[str, dict]:
        country_id = self._country_id(country_code)
        entry = self._catalogue(country_id).get(str(service_code).lower())
        if entry is None:
            raise ProviderError("That service is not offered for that country.")
        return country_id, entry

    def get_countries(self) -> list[ProviderCountryDTO]:
        selling = {str(c).strip().upper()
                   for c in settings.VERIFYGH.get("MARKETPLACE_COUNTRIES", []) if str(c).strip()}
        return [ProviderCountryDTO(code=iso, name="United States")
                for iso in COUNTRY_IDS if not selling or iso in selling]

    def get_services(self, *, priority=None, time_budget=None,
                     skip=None) -> list[ProviderServiceDTO]:
        """Priced services already in our catalogue: two public calls per country."""
        from apps.catalog.models import Service

        known = set(Service.objects.values_list("slug", flat=True))
        offerings = [
            ProviderServiceDTO(code=slug, name=slug, country_code=country.code,
                               cost=entry["cost"], currency="USD",
                               available=entry["count"] > 0, available_count=entry["count"],
                               ttl_minutes=20)
            for country in self.get_countries()
            for slug, entry in self._catalogue(self._country_id(country.code)).items()
            if slug in known
        ]
        logger.info("numberotp_catalog_listed", extra={"offerings": len(offerings)})
        return offerings

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        return self._entry(service_code, country_code)[1]["cost"]

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        try:
            _, entry = self._entry(service_code, country_code)
        except ProviderError:
            return AvailabilityDTO(available=False, count=0, note="Not offered.")
        return AvailabilityDTO(available=entry["count"] > 0, count=entry["count"])

    # -- orders ----------------------------------------------------------

    def create_order(self, service_code: str, country_code: str,
                     idempotency_key: str) -> ProviderOrderDTO:
        country_id, entry = self._entry(service_code, country_code)
        status, payload = self._call("POST", "/activations", idempotency_key=idempotency_key,
                                     json={"service": entry["code"], "country": country_id,
                                           "pool": "auto", "max_price": float(entry["cost"])})
        data = self._data(payload)
        activation_id = str(data.get("id") or "")
        if status >= 400 or not activation_id:
            code = str(payload.get("code") or status)[:40]
            operational = status == 402
            (logger.error if operational else logger.warning)(
                "numberotp_order_refused", extra={"status": status, "provider_code": code})
            error = ProviderError("Verification is temporarily unavailable." if operational
                                  else "No number is available for that service right now.")
            error.provider_code = code
            error.operational = operational
            raise error
        number = _e164(data.get("phoneNumber"))
        logger.info("numberotp_order_created", extra={"order": activation_id,
                                                      "has_number": bool(number)})
        return ProviderOrderDTO(
            provider_order_id=activation_id,
            state=ProviderOrderState.WAITING_FOR_CODE if number else ProviderOrderState.PENDING,
            phone_number=number, expires_at=_when(data.get("expiresAt")),
            cost=entry["cost"], currency="USD", raw={"id": activation_id})

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        status, payload = self._call("GET", f"/activations/{provider_order_id}")
        if status == 404:
            return ProviderOrderDTO(provider_order_id=provider_order_id,
                                    state=ProviderOrderState.EXPIRED,
                                    failure_reason="The provider no longer has this number.")
        if status >= 400:
            raise ProviderError("The verification provider could not complete that request.")
        data = self._data(payload)
        said = str(data.get("status") or "").lower()
        otp = str(data.get("otp") or "").strip()
        if otp:
            state = (ProviderOrderState.COMPLETED if said == "finished"
                     else ProviderOrderState.CODE_RECEIVED)
        else:
            state = _STATES.get(said, ProviderOrderState.WAITING_FOR_CODE)
            if said not in _STATES:
                logger.warning("numberotp_unexpected_status", extra={"status": said[:20]})
        return ProviderOrderDTO(
            provider_order_id=provider_order_id, state=state,
            phone_number=_e164(data.get("phone_number")),
            expires_at=_when(data.get("expires_at")),
            cost=_decimal(data.get("cost")), currency="USD",
            code=CodeDTO(code=otp, full_text=str(data.get("full_sms") or "")) if otp else None,
            raw={"status": said[:20]})

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        return self.get_order_status(provider_order_id).code

    def cancel_order(self, provider_order_id: str) -> bool:
        """Refunds in full a number with no SMS; 409 once received or closed."""
        status, _ = self._call("POST", f"/activations/{provider_order_id}/cancel")
        logger.info("numberotp_cancel", extra={"order": provider_order_id,
                                               "accepted": status == 200})
        return status == 200

    def refund_order(self, provider_order_id: str) -> bool:
        return self.cancel_order(provider_order_id)

    # -- our account -----------------------------------------------------

    supports_balance = True

    def get_balance(self) -> BalanceDTO:
        status, payload = self._call("GET", "/me")
        data = self._data(payload)
        try:
            return BalanceDTO(available=Decimal(str(data["balance"])),
                              frozen=Decimal(str(data.get("on_hold") or 0)),
                              currency=str(data.get("currency") or "USD").upper())
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise ProviderError("The verification provider did not report a balance.") from exc

    def account_balance(self) -> Decimal | None:
        try:
            return self.get_balance().available
        except (ProviderError, ServiceUnavailable):
            return None

    def health_check(self) -> bool:
        return self.is_configured and self.account_balance() is not None
