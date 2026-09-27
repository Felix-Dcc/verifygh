"""OnlineSim adapter, built from their published API documentation.

Source of truth: https://onlinesim.io/docs/api/en/index, rendered from the
vendor's OpenAPI description at https://onlinesim.io/openapi_docs/Onlinesim-API-UN/.
Every path, parameter name, field name and constant below comes from that
document; `onlinesim_endpoints.json` records what was read and when, and
`tests/test_onlinesim.py` checks this module against it. Nothing here is
guessed.

How this adapter behaves, and why:

* Official HTTPS API only. No scraping, no browser automation, no working
  around authentication, CAPTCHAs, rate limits or payment controls.

* **The API key travels in the Authorization header**, although the
  documentation also permits `?apikey=`. Query strings end up in proxy logs,
  error trackers and browser history, and this key can spend our balance.

* **Only the code is requested, never the message body.** `getState` can return
  either; asking for `message_to_code=1` means the provider extracts the code
  and we never hold the rest of somebody's SMS. That is less data to leak, less
  to retain, and it avoids inventing our own extraction regex that could pick
  the wrong digits out of a sentence.

* **A code is proven by a message, not by a state name.** OnlineSim documents
  exactly one operation state (`TZ_NUM_WAIT`). Rather than guess at the others,
  every undocumented state maps to PENDING and the arrival of a message is what
  marks an order delivered. An unknown state can therefore delay an order; it
  can never make an unfinished one look complete.

* **Cancelling is not instant.** `setOperationOk` documents a protective
  interval - 120 seconds, or 300 for WhatsApp - during which an operation with
  no SMS cannot be closed. `cancel_order` reports that honestly instead of
  pretending it worked.

**AUTHORISATION.** Confirmed in writing by OnlineSim support on 2026-09-27:
"the API may be integrated into third-party software products. However, your
account will be held responsible for all actions taken by users who purchase
numbers." That permission is precisely what TextVerified refused, and it is why
this adapter exists.

Two things follow from the second sentence, and they are not optional. Every
customer's conduct is contractually ours, so the AUP gate, the abuse flags and
the risk scoring are load-bearing rather than decorative. And a single abusive
customer can cost us the whole supply, because the account that gets suspended
is ours.

Still outstanding: the concurrency ceiling. Support confirmed a standard limit
exists and can be raised case by case but did not state it. See
docs/PROVIDER_INTEGRATION.md.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

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

logger = logging.getLogger("verifygh.provider.onlinesim")

REQUEST_TIMEOUT = 20

_REFERENCE = Path(__file__).with_name("onlinesim_countries.json")


class _NotConfigured(ServiceUnavailable):
    code = "PROVIDER_NOT_CONFIGURED"
    message = "This provider is not available yet."


def _decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class _CountryCodes:
    """Dial code -> ISO alpha-2, loaded once from the reference file.

    Kept out of the adapter body so the mapping can be reviewed and corrected as
    data. An unmappable dial code returns None and the caller drops the
    offering: a wrong country is worse than a missing one, because the customer
    pays for a number that cannot receive their verification.
    """

    _by_dial: dict[str, str] = {}
    _ambiguous: dict[str, dict[str, str]] = {}
    _loaded = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        try:
            data = json.loads(_REFERENCE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("onlinesim_country_reference_unreadable")
            data = {}
        cls._by_dial = {str(k): str(v) for k, v in (data.get("by_dial_code") or {}).items()}
        cls._ambiguous = {
            str(code): {str(n).lower(): str(iso) for n, iso in names.items()
                        if not str(n).startswith("_")}
            for code, names in (data.get("ambiguous") or {}).items()
            if not str(code).startswith("_")
        }
        cls._loaded = True

    @classmethod
    def resolve(cls, dial_code, name: str = "") -> str | None:
        cls._load()
        dial = str(dial_code).strip().lstrip("+")
        if not dial:
            return None

        shared = cls._ambiguous.get(dial)
        if shared is not None:
            # Shared codes are decided by the name the provider gave us, never
            # by picking the biggest country.
            return shared.get(str(name).strip().lower())

        return cls._by_dial.get(dial)


class OnlineSimProvider(VerificationProvider):
    """Single-service SMS activations from OnlineSim."""

    key = "onlinesim"
    display_name = "OnlineSim"

    # Their terms carry no clause forbidding us from relaying the code to the
    # customer who paid for the number. DISPLAY_VERIFICATION_CODES still governs
    # whether we actually do.
    permits_code_display = True

    # A webhook exists, but it is documented with no signature of any kind, so
    # nothing it says can be trusted. Leaving this False keeps the platform on
    # authenticated polling, which is the only source we can verify.
    supports_webhooks = False

    BASE_URL = "https://onlinesim.io"

    PATH_TARIFFS = "/api/getTariffs.php"
    PATH_ORDER = "/api/getNum.php"
    PATH_STATE = "/api/getState.php"
    PATH_REVISE = "/api/setOperationRevise.php"
    PATH_CLOSE = "/api/setOperationOk.php"
    PATH_BALANCE = "/api/getBalance.php"

    #: The only operation state OnlineSim documents. Everything else is unknown
    #: by definition and handled as PENDING.
    STATE_WAITING = "TZ_NUM_WAIT"

    #: Documented error codes, mapped to something a customer can act on.
    ERROR_MESSAGES = {
        "NO_NUMBER": "No number is available for that service right now.",
        "ERROR_NO_SERVICE": "That service is not offered at the moment.",
        "ERROR_NO_OPERATIONS": "That order is no longer active with the provider.",
        "WARNING_LOW_BALANCE": "Verification is temporarily unavailable.",
        "ACCOUNT_BLOCKED": "Verification is temporarily unavailable.",
        "ERROR_WRONG_KEY": "Verification is temporarily unavailable.",
        "ERROR_NO_KEY": "Verification is temporarily unavailable.",
        "ERROR_UNDEFINED": "The verification provider could not complete that request.",
    }

    #: Errors that mean "us", not "the customer" - worth an alert, not a retry.
    OPERATIONAL_ERRORS = {
        "WARNING_LOW_BALANCE", "ACCOUNT_BLOCKED", "ERROR_WRONG_KEY", "ERROR_NO_KEY",
    }

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PROVIDER_CREDENTIALS.get(self.key, {})
        self.api_key = str(self.config.get("api_key") or credentials.get("api_key") or "")
        self.base_url = str(
            self.config.get("base_url") or credentials.get("base_url") or self.BASE_URL
        ).rstrip("/")
        self._session = requests.Session()

    # -- plumbing --------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _require_configured(self, what: str) -> None:
        if not self.is_configured:
            logger.error("provider_not_configured", extra={"operation": what})
            raise _NotConfigured()

    def _request(self, path: str, params: dict | None = None):
        """One documented GET. Provider internals never reach the caller."""
        self._require_configured(path)

        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        # English, so the error strings and service names we log and store are
        # readable. The documented default is Russian.
        clean.setdefault("lang", "en")

        try:
            response = self._session.get(
                f"{self.base_url}{path}",
                params=clean,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.Timeout as exc:
            logger.warning("onlinesim_timeout", extra={"path": path})
            raise ProviderError("The verification provider did not respond in time.") from exc
        except requests.RequestException as exc:
            logger.warning("onlinesim_transport_error", extra={"path": path})
            raise ProviderError("We could not reach the verification provider.") from exc

        if response.status_code == 429:
            logger.warning("onlinesim_rate_limited", extra={"path": path})
            raise ServiceUnavailable(
                "The verification provider is busy. Please try again shortly.",
                code="PROVIDER_RATE_LIMITED",
            )
        if response.status_code in (401, 403):
            logger.error("onlinesim_unauthorised",
                         extra={"path": path, "status": response.status_code})
            raise ProviderError("The verification provider rejected our credentials.")

        try:
            payload = response.json() if response.content else {}
        except ValueError as exc:
            logger.error("onlinesim_unreadable_response",
                         extra={"path": path, "status": response.status_code})
            raise ProviderError(
                "The verification provider returned an unreadable response."
            ) from exc

        if response.status_code >= 400:
            logger.error("onlinesim_http_error",
                         extra={"path": path, "status": response.status_code})
            raise ProviderError("The verification provider could not complete that request.")

        return payload

    def _check(self, payload, path: str):
        """Raise on a documented error code, otherwise hand the payload back.

        OnlineSim answers 200 for business failures and signals them in a
        `response` field, so the HTTP status alone says nothing. `getState`
        answers with a bare array on success, which is its own success signal.
        """
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            raise ProviderError("The verification provider returned an unexpected response.")

        flag = payload.get("response")
        if flag in (1, "1", True):
            return payload

        code = str(flag or "")[:60]
        if code in self.OPERATIONAL_ERRORS:
            # Ours to fix - an empty upstream balance or a blocked account stops
            # every order, so it must be loud rather than look like bad luck.
            logger.error("onlinesim_operational_error",
                         extra={"path": path, "provider_code": code})
        else:
            logger.warning("onlinesim_error", extra={"path": path, "provider_code": code})

        raise ProviderError(
            self.ERROR_MESSAGES.get(code)
            or "The verification provider could not complete that request."
        )

    def _get(self, path: str, params: dict | None = None):
        return self._check(self._request(path, params), path)

    # -- catalog ---------------------------------------------------------

    def _tariffs(self, country_dial: str | int | None = None, page: int = 1) -> dict:
        params: dict = {"page": page}
        if country_dial is not None:
            params["country"] = country_dial
        payload = self._get(self.PATH_TARIFFS, params)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _unprefix(mapping) -> dict:
        """`{"_vkcom": {...}}` -> `{"vkcom": {...}}`.

        OnlineSim prefixes every key with an underscore so the JSON object keys
        stay strings in PHP. The prefix carries no meaning.
        """
        if not isinstance(mapping, dict):
            return {}
        return {
            str(key)[1:] if str(key).startswith("_") else str(key): value
            for key, value in mapping.items()
            if isinstance(value, dict)
        }

    def get_countries(self) -> list[ProviderCountryDTO]:
        payload = self._tariffs()
        countries: list[ProviderCountryDTO] = []
        skipped = 0

        for entry in self._unprefix(payload.get("countries")).values():
            if not entry.get("enable", True):
                continue
            dial = entry.get("code")
            name = str(entry.get("name") or "")
            iso = _CountryCodes.resolve(dial, name)
            if iso is None:
                skipped += 1
                continue
            countries.append(
                ProviderCountryDTO(code=iso, name=name or iso, dial_code=f"+{dial}")
            )

        if skipped:
            # Not an error. It is the adapter refusing to guess, and it should be
            # visible so the reference file can be extended deliberately.
            logger.info("onlinesim_countries_unmapped", extra={"skipped": skipped})
        return countries

    def get_services(self) -> list[ProviderServiceDTO]:
        """Every priced (service, country) offering, bounded by the catalog limit.

        `getTariffs` returns the service list for one country at a time, so this
        walks countries and stops at PROVIDER_CATALOG_LIMIT. Without a bound, a
        sync would make hundreds of upstream calls every few hours to list
        services nobody in Ghana buys.
        """
        limit = int(settings.VERIFYGH["PROVIDER_CATALOG_LIMIT"])
        offerings: list[ProviderServiceDTO] = []

        for country in self.get_countries():
            if len(offerings) >= limit:
                break
            dial = country.dial_code.lstrip("+")
            try:
                payload = self._tariffs(dial)
            except ProviderError:
                # One unavailable country must not empty the whole catalogue.
                logger.warning("onlinesim_country_tariffs_failed",
                               extra={"country": country.code})
                continue

            for slug, entry in self._unprefix(payload.get("services")).items():
                if len(offerings) >= limit:
                    break
                price = _decimal(entry.get("price"), Decimal("-1"))
                if price <= 0:
                    # A service we cannot price is left out rather than listed at
                    # a guessed cost.
                    continue
                count = _int(entry.get("count"), 0)
                offerings.append(
                    ProviderServiceDTO(
                        code=str(entry.get("slug") or slug),
                        name=str(entry.get("service") or slug),
                        country_code=country.code,
                        cost=price,
                        currency=self._currency(),
                        supports_sms=True,
                        supports_voice=False,
                        available=count > 0,
                        available_count=count,
                        ttl_minutes=int(settings.VERIFYGH["ORDER_TTL_MINUTES"]),
                    )
                )

        logger.info("onlinesim_catalog_listed", extra={"offerings": len(offerings)})
        return offerings

    def _currency(self) -> str:
        """Prices come back in the profile's own currency, USD unless changed."""
        return str(
            settings.PROVIDER_CREDENTIALS.get(self.key, {}).get("currency") or "USD"
        ).upper()

    def _service_entry(self, service_code: str, country_code: str) -> dict:
        dial = self._dial_for(country_code)
        payload = self._tariffs(dial)
        services = self._unprefix(payload.get("services"))
        entry = services.get(service_code)
        if entry is None:
            raise ProviderError("That service is not offered for that country.")
        return entry

    def _dial_for(self, country_code: str) -> str:
        """ISO alpha-2 -> dial code, by reversing the reference table."""
        wanted = str(country_code).upper()
        _CountryCodes._load()
        for dial, iso in _CountryCodes._by_dial.items():
            if iso == wanted:
                return dial
        for dial, names in _CountryCodes._ambiguous.items():
            if wanted in names.values():
                return dial
        raise ProviderError("We do not offer numbers for that country.")

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        price = _decimal(self._service_entry(service_code, country_code).get("price"),
                         Decimal("-1"))
        if price <= 0:
            raise ProviderError("That service has no price available right now.")
        return price

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        try:
            entry = self._service_entry(service_code, country_code)
        except ProviderError:
            return AvailabilityDTO(available=False, count=0, note="Not offered.")
        count = _int(entry.get("count"), 0)
        return AvailabilityDTO(available=count > 0, count=count)

    # -- orders ----------------------------------------------------------

    def create_order(
        self, service_code: str, country_code: str, idempotency_key: str
    ) -> ProviderOrderDTO:
        """Reserve a number.

        `idempotency_key` is accepted to satisfy the interface but cannot be
        forwarded: `getNum` documents no idempotency parameter. The customer is
        still protected - `Order.idempotency_key` means a client retry returns
        the existing order rather than buying twice - but a request that times
        out after OnlineSim has issued a number leaves that number reserved and
        billed with no id returned to us. That residual cost is ours, and it is
        bounded by one activation price.
        """
        payload = self._get(
            self.PATH_ORDER,
            {
                "service": service_code,
                "country": self._dial_for(country_code),
                # Ask for the full detail form, so the number comes back on this
                # call instead of needing a second round trip to getState.
                "number": "true",
            },
        )

        tzid = str(payload.get("tzid") or "")
        if not tzid:
            logger.error("onlinesim_order_without_tzid")
            raise ProviderError("The verification provider did not return an order reference.")

        number = str(payload.get("number") or "")
        logger.info("onlinesim_order_created",
                    extra={"tzid": tzid, "has_number": bool(number)})

        return ProviderOrderDTO(
            provider_order_id=tzid,
            state=(ProviderOrderState.NUMBER_ASSIGNED if number
                   else ProviderOrderState.PENDING),
            phone_number=number,
            cost=_decimal(payload.get("sum")) or None,
            currency=self._currency(),
            raw={"tzid": tzid},
        )

    def _operation(self, provider_order_id: str) -> dict | None:
        """One operation from `getState`, or None if it is no longer active.

        `message_to_code=1` asks OnlineSim to return only the extracted code
        rather than the whole SMS - we have no business holding the rest of
        somebody's message, and their extraction beats a regex of ours.
        """
        try:
            payload = self._get(
                self.PATH_STATE,
                {"tzid": provider_order_id, "message_to_code": 1, "msg_list": 0},
            )
        except ProviderError:
            # Documented as ERROR_NO_OPERATIONS once an operation has closed or
            # expired. Reported as "gone", never as "delivered".
            logger.info("onlinesim_operation_absent", extra={"tzid": provider_order_id})
            return None

        operations = payload if isinstance(payload, list) else [payload]
        for entry in operations:
            if isinstance(entry, dict) and str(entry.get("tzid")) == str(provider_order_id):
                return entry
        return None

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        entry = self._operation(provider_order_id)

        if entry is None:
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.EXPIRED,
                failure_reason="The provider is no longer holding this number.",
            )

        message = str(entry.get("msg") or "").strip()
        raw_state = str(entry.get("response") or "")
        number = str(entry.get("number") or "")

        if message:
            # A message is observable proof; a state name is not.
            state = ProviderOrderState.CODE_RECEIVED
        elif raw_state == self.STATE_WAITING:
            state = (ProviderOrderState.WAITING_FOR_CODE if number
                     else ProviderOrderState.PENDING)
        else:
            # Undocumented state. Never finished - the expiry sweep settles it.
            logger.warning("onlinesim_unknown_state", extra={"state": raw_state[:40]})
            state = ProviderOrderState.PENDING

        return ProviderOrderDTO(
            provider_order_id=provider_order_id,
            state=state,
            phone_number=number,
            cost=_decimal(entry.get("sum")) or None,
            currency=self._currency(),
            code=CodeDTO(code=message, full_text="") if message else None,
            raw={"state": raw_state, "seconds_left": _int(entry.get("time"), 0)},
        )

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        return self.get_order_status(provider_order_id).code

    def request_next_message(self, provider_order_id: str) -> bool:
        """Ask for the next SMS when the first one was not the code.

        Not part of the provider interface - the order flow does not use it
        today - but documented, and the natural place for it is here rather than
        a second module that also knows OnlineSim's paths.
        """
        try:
            self._get(self.PATH_REVISE, {"tzid": provider_order_id})
            return True
        except ProviderError:
            logger.info("onlinesim_revise_refused", extra={"tzid": provider_order_id})
            return False

    def cancel_order(self, provider_order_id: str) -> bool:
        """Close the operation and release the number.

        OnlineSim documents a protective interval - 120 seconds, 300 for
        WhatsApp - during which an operation with no SMS cannot be closed. A
        cancel inside that window is refused upstream, and this returns False so
        the caller can say so rather than reporting a cancellation that did not
        happen.
        """
        try:
            self._get(self.PATH_CLOSE, {"tzid": provider_order_id})
        except ProviderError:
            logger.info("onlinesim_cancel_refused", extra={"tzid": provider_order_id})
            return False
        logger.info("onlinesim_order_cancelled", extra={"tzid": provider_order_id})
        return True

    def refund_order(self, provider_order_id: str) -> bool:
        """OnlineSim has no separate refund endpoint.

        Funds for an active operation are held as a frozen balance and returned
        when the operation is cancelled, so closing the operation *is* the
        refund. Calling cancel here keeps that single fact in one place.
        """
        return self.cancel_order(provider_order_id)

    # -- health ----------------------------------------------------------

    def account_balance(self) -> Decimal | None:
        """Our balance with the provider. None when it cannot be read."""
        try:
            payload = self._get(self.PATH_BALANCE)
        except (ProviderError, ServiceUnavailable):
            return None
        if not isinstance(payload, dict):
            return None
        return _decimal(payload.get("balance"), Decimal("0"))

    def health_check(self) -> bool:
        """Cheapest authenticated call there is: read the balance."""
        if not self.is_configured:
            return False
        try:
            return self.account_balance() is not None
        except Exception:
            return False
