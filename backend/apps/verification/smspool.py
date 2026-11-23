"""SMSPool adapter: one-time US verification numbers.

Built 23 Nov 2026 from SMSPool's published Postman collection, "SMSPool API"
(documenter.getpostman.com/view/30155063/2s9YXmZ1JY; JSON at
/api/collections/30155063/2s9YXmZ1JY), and nothing else:

    GET  /country/retrieve_all          [{ID, name, short_name, region}]
    GET  /service/retrieve_all?country= [{ID, name}]
    POST /request/pricing  country      [{service, pool, price, ...}]
    POST /request/price    country, service      {price, high_price, success_rate}
    POST /sms/stock        key, country, service {success, amount}
    POST /purchase/sms     key, country, service, max_price, pricing_option,
                           quantity, activation_type
                           -> {success: 1, order_id, number, expires_in, cost}
                           or {success: 0, type: OUT_OF_STOCK | PRICE_NOT_FOUND
                               | BALANCE_ERROR, message}
    POST /sms/check        key, orderid
                           -> {status: 1} pending, {status: 3, sms, full_sms}
                              complete, {status: 6} refunded; plus expiration
    POST /sms/cancel       key, orderid -> {success: 1 | 0}
    POST /request/balance  key -> {balance}

The API key goes in the POST body, as every documented request has it - never
in a query string, where proxies and error trackers would keep it.

**Only documented statuses are trusted.** 1, 3 and 6 are the only ones the
collection shows. A code is proven by a non-empty `sms`, never by a status
number; anything else waits until SMSPool's own expiration, then reads as
expired. An unknown status can delay an order, never complete one.

**Never above the listed price.** `create_order` asks SMSPool for the price
first and passes it as `max_price`, so we are never charged more than the cost
the customer's price was based on.

**No idempotency key.** `purchase/sms` documents none: a timeout after SMSPool
issued a number leaves it reserved and billed with no id returned to us. As
with OnlineSim, `Order.idempotency_key` still stops a customer retry buying
twice, and the loss is bounded by one number's price.

**AUTHORISATION.** SMSPool's Terms of Service, Article 11 "API use,
integrations and resale", effective 30 November 2026, covers making the
Services "available to your own customers". Its conditions (11.5) are ours to
meet: customers bound by terms protecting SMSPool, no sign-ups from its
restricted jurisdictions (9.1.1; Ghana is not one), every order traceable to a
customer, and no use of SMSPool's name. Staff record that in Admin > Providers
(`resale_authorized`) before anything is sold through it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
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

logger = logging.getLogger("verifygh.provider.smspool")

REQUEST_TIMEOUT = 20
CATALOGUE_CACHE_SECONDS = 6 * 3600

#: SMSPool names that bundle several apps, mapped to our service slug. Names
#: that already reduce to the slug (WhatsApp, Telegram, Signal) need no entry.
ALIASES = {
    "tiktokdouyin": "tiktok",
    "twitterx": "twitter",
    "googlegmail": "google",
    "instagramthreads": "instagram",
    "facebookmetaviewpoints": "facebook",
    "matchmeeticzweisam": "match",
}

STATUS_PENDING, STATUS_COMPLETE, STATUS_REFUNDED = 1, 3, 6

#: Purchase failures that are ours to fix, not the customer's bad luck.
OPERATIONAL_ERRORS = {"BALANCE_ERROR"}


def slug_for(name: str) -> str:
    """'Twitter / X' -> 'twitter'; 'Plenty Of Fish' -> 'plentyoffish'."""
    plain = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    return ALIASES.get(plain, plain)


def _decimal(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _e164(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}" if digits else ""


class SMSPoolProvider(VerificationProvider):
    key = "smspool"
    display_name = "SMSPool"
    permits_code_display = True
    supports_webhooks = False

    BASE_URL = "https://api.smspool.net"

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

    def _call(self, method: str, path: str, data: dict | None = None,
              params: dict | None = None, *, keyed: bool = True):
        if keyed and not self.is_configured:
            logger.error("provider_not_configured", extra={"operation": path})
            raise ServiceUnavailable("Verification is temporarily unavailable.",
                                     code="PROVIDER_NOT_CONFIGURED")
        body = dict(data or {})
        if keyed:
            body["key"] = self.api_key
        try:
            response = self._session.request(
                method, f"{self.base_url}{path}", data=body or None, params=params,
                headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            logger.warning("smspool_timeout", extra={"path": path})
            raise ProviderError("The verification provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("smspool_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the verification provider.") from exc

        if response.status_code == 429:
            logger.warning("smspool_rate_limited", extra={"path": path})
            raise ServiceUnavailable("The verification provider is busy. Please try again shortly.",
                                     code="PROVIDER_RATE_LIMITED")
        if response.status_code in (401, 403):
            logger.error("smspool_unauthorised", extra={"path": path,
                                                        "status": response.status_code})
            raise ProviderError("The verification provider rejected our credentials.")
        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("smspool_unreadable_response", extra={"path": path,
                                                               "status": response.status_code})
            raise ProviderError(
                "The verification provider returned an unreadable response.") from exc
        # Business failures come as 4xx with a JSON body; callers read `success`.
        if response.status_code >= 500:
            logger.error("smspool_http_error", extra={"path": path,
                                                      "status": response.status_code})
            raise ProviderError("The verification provider could not complete that request.")
        return payload

    # -- catalogue -------------------------------------------------------

    def _countries(self) -> list[dict]:
        cached = cache.get("smspool:countries")
        if cached is None:
            cached = self._call("GET", "/country/retrieve_all", keyed=False)
            if not isinstance(cached, list):
                raise ProviderError("The verification provider returned an unexpected response.")
            cache.set("smspool:countries", cached, CATALOGUE_CACHE_SECONDS)
        return cached

    def _country_id(self, country_code: str) -> int:
        wanted = str(country_code).upper()
        for entry in self._countries():
            if str(entry.get("short_name") or "").upper() == wanted:
                return int(entry["ID"])
        raise ProviderError("We do not offer numbers for that country.")

    def _service_ids(self, country_id: int) -> dict[str, int]:
        """Our slug -> SMSPool's service ID, for one country."""
        key = f"smspool:services:{country_id}"
        cached = cache.get(key)
        if cached is None:
            payload = self._call("GET", "/service/retrieve_all",
                                 params={"country": country_id}, keyed=False)
            if not isinstance(payload, list):
                raise ProviderError("The verification provider returned an unexpected response.")
            cached = {}
            for entry in payload:
                slug = slug_for(entry.get("name"))
                if slug and slug not in cached and entry.get("ID") is not None:
                    cached[slug] = int(entry["ID"])
            cache.set(key, cached, CATALOGUE_CACHE_SECONDS)
        return cached

    def _service_id(self, service_code: str, country_code: str) -> tuple[int, int]:
        country_id = self._country_id(country_code)
        service_id = self._service_ids(country_id).get(str(service_code).lower())
        if service_id is None:
            raise ProviderError("That service is not offered for that country.")
        return service_id, country_id

    def _selling(self) -> list[str]:
        return [str(code).strip().upper()
                for code in settings.VERIFYGH.get("MARKETPLACE_COUNTRIES", []) if str(code).strip()]

    def get_countries(self) -> list[ProviderCountryDTO]:
        selling = set(self._selling())
        return [ProviderCountryDTO(code=str(e["short_name"]).upper(), name=str(e.get("name") or ""))
                for e in self._countries()
                if e.get("short_name") and (not selling or str(e["short_name"]).upper() in selling)]

    def get_services(self, *, priority=None, time_budget=None,
                     skip=None) -> list[ProviderServiceDTO]:
        """The cheapest price per service, for services already in our catalogue.

        One pricing call per selling country. Only services VerifyGH already
        lists are offered, so SMSPool's own naming never adds duplicate or
        half-named entries to the shop.
        """
        from apps.catalog.models import Service

        known = set(Service.objects.values_list("slug", flat=True))
        offerings: list[ProviderServiceDTO] = []
        for country in self.get_countries():
            country_id = self._country_id(country.code)
            slugs = {sid: slug for slug, sid in self._service_ids(country_id).items()}
            prices = self._call("POST", "/request/pricing", {"country": country_id}, keyed=False)
            if not isinstance(prices, list):
                raise ProviderError("The verification provider returned an unexpected response.")
            cheapest: dict[str, Decimal] = {}
            for entry in prices:
                slug = slugs.get(entry.get("service"))
                price = _decimal(entry.get("price"))
                if slug in known and price and (slug not in cheapest or price < cheapest[slug]):
                    cheapest[slug] = price
            offerings += [
                ProviderServiceDTO(code=slug, name=slug, country_code=country.code, cost=price,
                                   currency="USD", reports_stock=False, ttl_minutes=20)
                for slug, price in cheapest.items()
            ]
        logger.info("smspool_catalog_listed", extra={"offerings": len(offerings)})
        return offerings

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        service_id, country_id = self._service_id(service_code, country_code)
        payload = self._call("POST", "/request/price",
                             {"country": country_id, "service": service_id}, keyed=False)
        price = _decimal(payload.get("price")) if isinstance(payload, dict) else None
        if price is None:
            raise ProviderError("That service has no price available right now.")
        return price

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        try:
            service_id, country_id = self._service_id(service_code, country_code)
        except ProviderError:
            return AvailabilityDTO(available=False, count=0, note="Not offered.")
        payload = self._call("POST", "/sms/stock", {"country": country_id, "service": service_id})
        try:
            count = int(payload.get("amount")) if isinstance(payload, dict) else 0
        except (TypeError, ValueError):
            count = 0
        return AvailabilityDTO(available=count > 0, count=count)

    # -- orders ----------------------------------------------------------

    def create_order(self, service_code: str, country_code: str,
                     idempotency_key: str) -> ProviderOrderDTO:
        price = self.get_pricing(service_code, country_code)
        service_id, _ = self._service_id(service_code, country_code)
        payload = self._call("POST", "/purchase/sms", {
            "country": str(country_code).upper(),
            "service": service_id,
            "max_price": f"{price}",
            "pricing_option": 1,   # best success rate, within max_price
            "quantity": 1,
            "activation_type": "SMS",
        })
        if not isinstance(payload, dict) or str(payload.get("success")) != "1":
            kind = str((payload or {}).get("type") or "")[:40] if isinstance(payload, dict) else ""
            if kind in OPERATIONAL_ERRORS:
                logger.error("smspool_operational_error", extra={"provider_code": kind})
            else:
                logger.warning("smspool_order_refused", extra={"provider_code": kind})
            error = ProviderError(
                "No number is available for that service right now."
                if kind in ("OUT_OF_STOCK", "PRICE_NOT_FOUND")
                else "Verification is temporarily unavailable.")
            error.provider_code = kind
            error.operational = kind in OPERATIONAL_ERRORS
            raise error

        order_id = str(payload.get("order_id") or "")
        if not order_id:
            logger.error("smspool_order_without_id")
            raise ProviderError("The verification provider did not return an order reference.")
        expires_at = None
        try:
            expires_at = datetime.fromtimestamp(int(payload["expiration"]), tz=UTC)
        except (KeyError, TypeError, ValueError):
            pass
        number = _e164(payload.get("number"))
        logger.info("smspool_order_created", extra={"order": order_id, "has_number": bool(number)})
        return ProviderOrderDTO(
            provider_order_id=order_id,
            state=ProviderOrderState.WAITING_FOR_CODE if number else ProviderOrderState.PENDING,
            phone_number=number, expires_at=expires_at,
            cost=_decimal(payload.get("cost")), currency="USD", raw={"order_id": order_id})

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        payload = self._call("POST", "/sms/check", {"orderid": provider_order_id})
        if not isinstance(payload, dict):
            raise ProviderError("The verification provider returned an unexpected response.")
        status = payload.get("status")
        sms = str(payload.get("sms") or "").strip()
        try:
            expiration = int(payload.get("expiration"))
        except (TypeError, ValueError):
            expiration = None

        if sms:
            state = ProviderOrderState.CODE_RECEIVED  # a message is the proof
        elif str(status) == str(STATUS_REFUNDED):
            state = ProviderOrderState.CANCELLED
        elif expiration and time.time() > expiration:
            state = ProviderOrderState.EXPIRED
        else:
            if str(status) != str(STATUS_PENDING):
                logger.warning("smspool_unknown_status", extra={"status": str(status)[:20]})
            state = ProviderOrderState.WAITING_FOR_CODE

        return ProviderOrderDTO(
            provider_order_id=provider_order_id, state=state,
            expires_at=datetime.fromtimestamp(expiration, tz=UTC) if expiration else None,
            code=CodeDTO(code=sms, full_text=str(payload.get("full_sms") or "")) if sms else None,
            failure_reason=("The provider refunded this number."
                            if state == ProviderOrderState.CANCELLED else ""),
            raw={"status": str(status)[:20]})

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        return self.get_order_status(provider_order_id).code

    def cancel_order(self, provider_order_id: str) -> bool:
        """SMSPool refunds a cancelled order; it may refuse one too young to cancel."""
        payload = self._call("POST", "/sms/cancel", {"orderid": provider_order_id})
        ok = isinstance(payload, dict) and str(payload.get("success")) == "1"
        logger.info("smspool_cancel", extra={"order": provider_order_id, "accepted": ok})
        return ok

    def refund_order(self, provider_order_id: str) -> bool:
        return self.cancel_order(provider_order_id)

    # -- our account -----------------------------------------------------

    supports_balance = True

    def get_balance(self) -> BalanceDTO:
        payload = self._call("POST", "/request/balance")
        balance = payload.get("balance") if isinstance(payload, dict) else None
        try:
            return BalanceDTO(available=Decimal(str(balance)), currency="USD")
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ProviderError("The verification provider did not report a balance.") from exc

    def account_balance(self) -> Decimal | None:
        try:
            return self.get_balance().available
        except (ProviderError, ServiceUnavailable):
            return None

    def health_check(self) -> bool:
        return self.is_configured and self.account_balance() is not None
