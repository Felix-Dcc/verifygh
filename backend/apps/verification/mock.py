"""A full-fidelity mock verification provider.

This exists so the entire product - marketplace, ordering, live order screen,
refunds, admin - can be built, demoed and tested end to end with no upstream
credentials and no real money.

It simulates the states that actually matter operationally:

    HAPPY        number assigned, code arrives, order completes
    SLOW_CODE    code arrives late, exercising the waiting UI and the TTL
    NO_CODE      number assigned, nothing ever arrives -> expiry -> auto refund
    NO_STOCK     provider has no number -> order fails -> immediate refund
    PROVIDER_ERR provider call raises -> order fails -> immediate refund

State lives in the Django cache so the API process and Celery workers agree on
what a given mock order is doing.
"""

from __future__ import annotations

import logging
import random
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.common.errors import ProviderError
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

logger = logging.getLogger("verifygh.provider.mock")

CACHE_PREFIX = "mockprov:"
CACHE_TTL = 60 * 60 * 6

#: The mock account balance, in USD, unless a test sets one with set_balance().
MOCK_BALANCE = Decimal("1000.00")

#: Tests set this to force a scenario. None means "pick by weight".
FORCE_SCENARIO: str | None = None

SCENARIO_WEIGHTS = {
    "HAPPY": 80,
    "SLOW_CODE": 10,
    "NO_CODE": 5,
    "NO_STOCK": 3,
    "PROVIDER_ERR": 2,
}

# Seconds after creation at which each step happens, per scenario.
SCENARIO_TIMINGS = {
    # The number comes back with the reservation, as it does upstream; only the
    # inbound SMS is delayed. "assign" is kept so an asynchronous provider can
    # be simulated by raising it.
    "HAPPY": {"assign": 0, "code": 8},
    "SLOW_CODE": {"assign": 0, "code": 45},
    "NO_CODE": {"assign": 0, "code": None},
    "NO_STOCK": {"assign": None, "code": None},
    "PROVIDER_ERR": {"assign": None, "code": None},
}

MOCK_COUNTRIES = [
    ProviderCountryDTO(code="US", name="United States", dial_code="+1"),
    ProviderCountryDTO(code="GB", name="United Kingdom", dial_code="+44"),
    ProviderCountryDTO(code="CA", name="Canada", dial_code="+1"),
    ProviderCountryDTO(code="NL", name="Netherlands", dial_code="+31"),
    ProviderCountryDTO(code="DE", name="Germany", dial_code="+49"),
]

DIAL_CODES = {country.code: country.dial_code for country in MOCK_COUNTRIES}

# (service code, display name, base USD cost, sms, voice)
MOCK_SERVICES = [
    ("instagram", "Instagram", Decimal("0.90"), True, False),
    ("whatsapp", "WhatsApp", Decimal("1.40"), True, True),
    ("telegram", "Telegram", Decimal("1.10"), True, True),
    ("google", "Google", Decimal("1.25"), True, True),
    ("facebook", "Facebook", Decimal("0.95"), True, False),
    ("tiktok", "TikTok", Decimal("0.85"), True, False),
    ("discord", "Discord", Decimal("0.70"), True, False),
    ("x", "X", Decimal("1.05"), True, False),
    ("github", "GitHub", Decimal("1.30"), True, False),
    ("openai", "OpenAI", Decimal("1.60"), True, False),
    ("linkedin", "LinkedIn", Decimal("1.15"), True, False),
    ("amazon", "Amazon", Decimal("1.00"), True, True),
    ("uber", "Uber", Decimal("1.20"), True, True),
    ("airbnb", "Airbnb", Decimal("1.35"), True, False),
    ("paypal", "PayPal", Decimal("1.80"), True, False),
    ("signal", "Signal", Decimal("1.45"), True, True),
]


#: Mock rental prices in USD by days, shaped like TextVerified's (14 Oct 2026):
#: a single-service number, and "allservices", which has no one-day rental.
MOCK_RENTAL_PRICES = {
    "single": {1: Decimal("1.90"), 3: Decimal("2.40"), 7: Decimal("3.00"),
               14: Decimal("3.80"), 30: Decimal("4.80"), 90: Decimal("13.90")},
    "allservices": {3: Decimal("5.50"), 7: Decimal("7.00"), 14: Decimal("8.20"),
                    30: Decimal("10.00"), 90: Decimal("28.90")},
}

#: A mock rental can be refunded for this long after it starts, as long as no
#: message has arrived - roughly how TextVerified's `refund.canRefund` behaves.
MOCK_RENTAL_REFUND_MINUTES = 20

#: In the default mode a first message lands this long after the rental starts,
#: so the inbox can be seen working in a local preview.
MOCK_RENTAL_FIRST_SMS_SECONDS = 15

RENTAL_PREFIX = f"{CACHE_PREFIX}rental:"


def _key(provider_order_id: str) -> str:
    return f"{CACHE_PREFIX}{provider_order_id}"


def _pick_scenario() -> str:
    if FORCE_SCENARIO:
        return FORCE_SCENARIO
    population = list(SCENARIO_WEIGHTS)
    weights = [SCENARIO_WEIGHTS[name] for name in population]
    return random.choices(population, weights=weights, k=1)[0]


def _fake_number(country_code: str) -> str:
    dial = DIAL_CODES.get(country_code, "+1")
    body = "".join(secrets.choice("0123456789") for _ in range(10 if dial == "+1" else 9))
    return f"{dial}{body}"


def _fake_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))


class MockVerificationProvider(VerificationProvider):
    key = "mock"
    display_name = "Mock provider (development)"
    permits_code_display = True
    supports_webhooks = False

    # -- catalog ---------------------------------------------------------

    def get_countries(self) -> list[ProviderCountryDTO]:
        return list(MOCK_COUNTRIES)

    def get_services(self, *, priority=None, time_budget=None,
                     skip=None) -> list[ProviderServiceDTO]:
        offerings: list[ProviderServiceDTO] = []
        for country in MOCK_COUNTRIES:
            for code, name, cost, sms, voice in MOCK_SERVICES:
                # Deterministic per (service, country) so a demo does not flicker.
                seed = sum(ord(char) for char in f"{code}{country.code}")
                multiplier = Decimal("1.00") + Decimal(seed % 40) / Decimal("100")
                available = seed % 11 != 0
                offerings.append(
                    ProviderServiceDTO(
                        code=code,
                        name=name,
                        country_code=country.code,
                        cost=(cost * multiplier).quantize(Decimal("0.0001")),
                        currency="USD",
                        supports_sms=sms,
                        supports_voice=voice,
                        available=available,
                        available_count=None if not available else 5 + (seed % 90),
                        ttl_minutes=20,
                    )
                )
        return offerings

    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        for offering in self.get_services():
            if offering.code == service_code and offering.country_code == country_code:
                return offering.cost
        raise ProviderError("That service is not offered for this country.")

    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        for offering in self.get_services():
            if offering.code == service_code and offering.country_code == country_code:
                return AvailabilityDTO(
                    available=offering.available, count=offering.available_count
                )
        return AvailabilityDTO(available=False, count=0, note="Not offered.")

    # -- orders ----------------------------------------------------------

    def create_order(
        self, service_code: str, country_code: str, idempotency_key: str
    ) -> ProviderOrderDTO:
        # Honour the idempotency key the way a real provider would: the same key
        # returns the same reservation instead of booking a second number.
        existing_id = cache.get(f"{CACHE_PREFIX}idem:{idempotency_key}")
        if existing_id:
            return self.get_order_status(existing_id)

        balance = cache.get(f"{CACHE_PREFIX}balance:{self.key}")
        if balance not in (None, "error") and Decimal(str(balance)) < self.get_pricing(
                service_code, country_code):
            error = ProviderError("Verification is temporarily unavailable.")
            error.provider_code = "WARNING_LOW_BALANCE"
            error.operational = True
            raise error

        scenario = _pick_scenario()

        if scenario == "PROVIDER_ERR":
            logger.info("mock_provider_simulated_error")
            raise ProviderError("The provider rejected the request.")

        provider_order_id = f"mock_{secrets.token_hex(8)}"
        now = timezone.now()

        if scenario == "NO_STOCK":
            state = {
                "scenario": scenario,
                "service": service_code,
                "country": country_code,
                "created_at": now.isoformat(),
                "failed": True,
                "failure_reason": "NO_NUMBERS_AVAILABLE",
            }
            cache.set(_key(provider_order_id), state, CACHE_TTL)
            cache.set(f"{CACHE_PREFIX}idem:{idempotency_key}", provider_order_id, CACHE_TTL)
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.FAILED,
                failure_reason="No numbers are available for this service right now.",
            )

        timings = SCENARIO_TIMINGS[scenario]
        state = {
            "scenario": scenario,
            "service": service_code,
            "country": country_code,
            "created_at": now.isoformat(),
            "assign_after": timings["assign"],
            "code_after": timings["code"],
            "phone": _next_forced_number() or _fake_number(country_code),
            "code": _fake_code(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
            "cancelled": False,
            "completed": False,
            "failed": False,
            "failure_reason": "",
        }
        cache.set(_key(provider_order_id), state, CACHE_TTL)
        cache.set(f"{CACHE_PREFIX}idem:{idempotency_key}", provider_order_id, CACHE_TTL)
        logger.info(
            "mock_order_created",
            extra={"provider_order_id": provider_order_id, "scenario": scenario},
        )
        return self.get_order_status(provider_order_id)

    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        state = cache.get(_key(provider_order_id))
        if state is None:
            raise ProviderError("Unknown provider order.")

        created_at = datetime.fromisoformat(state["created_at"])
        elapsed = (timezone.now() - created_at).total_seconds()

        if state.get("failed"):
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.FAILED,
                failure_reason=state.get("failure_reason", "Provider failure."),
            )
        if state.get("cancelled"):
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.CANCELLED,
                phone_number=state.get("phone", ""),
            )

        expires_at = datetime.fromisoformat(state["expires_at"])
        assign_after = state.get("assign_after")
        code_after = state.get("code_after")

        if assign_after is None or elapsed < assign_after:
            return ProviderOrderDTO(
                provider_order_id=provider_order_id, state=ProviderOrderState.PENDING
            )

        code_ready = code_after is not None and elapsed >= code_after

        if code_ready and timezone.now() <= expires_at:
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.CODE_RECEIVED,
                phone_number=state["phone"],
                expires_at=expires_at,
                code=CodeDTO(
                    code=state["code"],
                    full_text=f"{state['code']} is your verification code.",
                    received_at=created_at + timedelta(seconds=code_after),
                ),
            )

        if timezone.now() > expires_at:
            return ProviderOrderDTO(
                provider_order_id=provider_order_id,
                state=ProviderOrderState.EXPIRED,
                phone_number=state["phone"],
                expires_at=expires_at,
            )

        return ProviderOrderDTO(
            provider_order_id=provider_order_id,
            state=ProviderOrderState.WAITING_FOR_CODE,
            phone_number=state["phone"],
            expires_at=expires_at,
        )

    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        status = self.get_order_status(provider_order_id)
        return status.code

    def cancel_order(self, provider_order_id: str) -> bool:
        state = cache.get(_key(provider_order_id))
        if state is None:
            return False
        # A real provider refuses to cancel once a code has landed; mirror that.
        if self.get_order_status(provider_order_id).state == ProviderOrderState.CODE_RECEIVED:
            return False
        state["cancelled"] = True
        cache.set(_key(provider_order_id), state, CACHE_TTL)
        return True

    def refund_order(self, provider_order_id: str) -> bool:
        state = cache.get(_key(provider_order_id))
        if state is None:
            return False
        status = self.get_order_status(provider_order_id)
        # Providers refund unused reservations, not delivered ones.
        return status.state in {
            ProviderOrderState.FAILED,
            ProviderOrderState.CANCELLED,
            ProviderOrderState.EXPIRED,
        }

    supports_issue_reports = True

    def report_number_issue(self, provider_order_id: str, reason: str) -> bool | None:
        return cache.get(_key(provider_order_id)) is not None

    def release_retry_after_seconds(self, service_code: str) -> int:
        return 1

    # -- rentals -----------------------------------------------------------

    supports_rentals = True

    @staticmethod
    def _rental_prices(service_code: str) -> dict:
        return MOCK_RENTAL_PRICES["allservices" if service_code == "allservices" else "single"]

    def rental_price(self, service_code: str, days: int) -> Decimal | None:
        if _rental_mode() == "PROVIDER_ERR":
            raise ProviderError("The verification provider did not respond in time.")
        override = cache.get(f"{RENTAL_PREFIX}price:{service_code}:{days}")
        if override is not None:
            return Decimal(str(override))
        return self._rental_prices(service_code).get(int(days))

    def rental_stock(self, service_code: str, days: int) -> int:
        if _rental_mode() == "NO_STOCK":
            return 0
        return 9000 if self.rental_price(service_code, days) is not None else 0

    def create_rental(self, service_code: str, days: int, idempotency_key: str) -> RentalDTO:
        mode = _rental_mode()
        known = cache.get(f"{RENTAL_PREFIX}key:{idempotency_key}")
        if known:
            # The same key answers with the same purchase, as upstream.
            return self.get_rental_sale(known)
        if mode == "REFUSE":
            refused = ProviderError("No number is available for that service right now.")
            refused.provider_code = "Unavailable"
            refused.http_status = 400
            raise refused
        price = self.rental_price(service_code, days)
        if price is None:
            refused = ProviderError("The verification provider could not complete that.")
            refused.provider_code = "BadRequest"
            refused.http_status = 400
            raise refused

        rental_id = f"mock-rnt-{secrets.token_hex(6)}"
        now = timezone.now()
        state = {
            "id": rental_id,
            "service": service_code,
            "phone": _next_forced_number() or _fake_number("US"),
            "created_at": now.isoformat(),
            "ends_at": (now + timedelta(days=int(days))).isoformat(),
            "price": str(price),
            "state": "ACTIVE",
            # Further reads still processing (PENDING mode answers the purchase itself so).
            "pending_reads": 0,
            "messages": [],
            "quiet": mode == "QUIET",
            "refundable": True,
        }
        cache.set(f"{RENTAL_PREFIX}{rental_id}", state, CACHE_TTL)
        cache.set(f"{RENTAL_PREFIX}key:{idempotency_key}", rental_id, CACHE_TTL)
        if mode == "TIMEOUT":
            # The purchase went through, but the answer never reached us.
            _set_rental_mode(None)
            raise ProviderError("The verification provider did not respond in time.")
        if mode == "PENDING":
            return RentalDTO(state=RentalState.PENDING, sale_id=rental_id, cost=price)
        return self._rental_dto(state)

    def get_rental_sale(self, sale_id: str) -> RentalDTO:
        state = cache.get(f"{RENTAL_PREFIX}{sale_id}")
        if state is None:
            missing = ProviderError("The verification provider does not recognise that request.")
            missing.http_status = 404
            raise missing
        if state["pending_reads"] > 0:
            state["pending_reads"] -= 1
            cache.set(f"{RENTAL_PREFIX}{sale_id}", state, CACHE_TTL)
            return RentalDTO(state=RentalState.PENDING, sale_id=sale_id,
                             cost=Decimal(state["price"]))
        return self._rental_dto(state)

    def get_rental(self, provider_rental_id: str) -> RentalDTO:
        state = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
        if state is None:
            missing = ProviderError("The verification provider does not recognise that request.")
            missing.http_status = 404
            raise missing
        return self._rental_dto(state)

    def _rental_dto(self, state: dict) -> RentalDTO:
        now = timezone.now()
        created = datetime.fromisoformat(state["created_at"])
        ends_at = datetime.fromisoformat(state["ends_at"])
        refundable_until = created + timedelta(minutes=MOCK_RENTAL_REFUND_MINUTES)
        kind = state["state"]
        if kind == "ACTIVE" and ends_at <= now:
            kind = "EXPIRED"
        can_refund = (kind == "ACTIVE" and state.get("refundable", True)
                      and now < refundable_until and not self._mock_messages(state))
        return RentalDTO(
            state=RentalState(kind),
            provider_rental_id=state["id"],
            sale_id=state["id"],
            phone_number=state["phone"],
            ends_at=ends_at,
            can_refund=can_refund,
            refundable_until=refundable_until,
            cost=Decimal(state["price"]),
        )

    def refund_rental(self, provider_rental_id: str) -> bool:
        state = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
        if state is None or not self._rental_dto(state).can_refund:
            return False
        state["state"] = "REFUNDED"
        cache.set(f"{RENTAL_PREFIX}{provider_rental_id}", state, CACHE_TTL)
        return True

    def extend_rental(self, provider_rental_id: str, days: int) -> RentalExtensionDTO:
        state = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
        if state is None or self._rental_dto(state).state != RentalState.ACTIVE:
            refused = ProviderError("The verification provider could not complete that.")
            refused.provider_code = "BadRequest"
            refused.http_status = 400
            raise refused
        if _rental_mode() == "REFUSE":
            refused = ProviderError("The verification provider could not complete that.")
            refused.provider_code = "BadRequest"
            refused.http_status = 400
            raise refused
        price = self.rental_price(state["service"], days)
        if price is None:
            refused = ProviderError("The verification provider could not complete that.")
            refused.provider_code = "BadRequest"
            refused.http_status = 400
            raise refused
        new_ends = datetime.fromisoformat(state["ends_at"]) + timedelta(days=int(days))
        state["ends_at"] = new_ends.isoformat()
        cache.set(f"{RENTAL_PREFIX}{provider_rental_id}", state, CACHE_TTL)
        return RentalExtensionDTO(provider_extension_id=f"mock-ext-{secrets.token_hex(4)}",
                                  new_ends_at=new_ends, cost=price)

    def _mock_messages(self, state: dict) -> list[dict]:
        messages = list(state.get("messages") or [])
        created = datetime.fromisoformat(state["created_at"])
        if not state.get("quiet") and (timezone.now() - created).total_seconds() >= \
                MOCK_RENTAL_FIRST_SMS_SECONDS:
            messages.insert(0, {
                "id": f"{state['id']}-sms-1",
                "body": "Your verification code is 482913. Do not share it.",
                "code": "482913",
                "sender": "22395",
                "at": (created + timedelta(seconds=MOCK_RENTAL_FIRST_SMS_SECONDS)).isoformat(),
            })
        return messages

    def rental_messages(self, provider_rental_id: str) -> list[RentalMessageDTO]:
        state = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
        if state is None:
            return []
        return [RentalMessageDTO(provider_message_id=item["id"], body=item["body"],
                                 code=item["code"], sender=item["sender"],
                                 received_at=datetime.fromisoformat(item["at"]))
                for item in self._mock_messages(state)]

    # -- our account ------------------------------------------------------

    supports_balance = True

    def get_balance(self) -> BalanceDTO:
        state = cache.get(f"{CACHE_PREFIX}balance:{self.key}")
        if state == "error":
            raise ProviderError("The verification provider did not report a balance.")
        available = Decimal(str(state)) if state is not None else MOCK_BALANCE
        return BalanceDTO(available=available, frozen=Decimal("0"), currency="USD")

    def health_check(self) -> bool:
        return True


# -- test helpers -----------------------------------------------------------


def force_numbers(numbers: list[str] | None) -> None:
    """Make the next mock orders hand out these numbers, in order.

    Lets a test reproduce a provider giving us a number we have seen before.
    """
    cache.set(f"{CACHE_PREFIX}forced_numbers", list(numbers or []), CACHE_TTL)


def _next_forced_number() -> str | None:
    queue = cache.get(f"{CACHE_PREFIX}forced_numbers") or []
    if not queue:
        return None
    number, rest = queue[0], queue[1:]
    cache.set(f"{CACHE_PREFIX}forced_numbers", rest, CACHE_TTL)
    return number


def set_balance(value, key: str = "mock") -> None:
    """Set the mock account balance (a number), "error" to fail the read, or None to reset.

    A balance below an offering's cost also makes `create_order` fail the way
    OnlineSim does, with WARNING_LOW_BALANCE. `key` is the adapter key, so a
    test can give a second mock adapter a balance of its own.
    """
    if value is None:
        cache.delete(f"{CACHE_PREFIX}balance:{key}")
    else:
        cache.set(f"{CACHE_PREFIX}balance:{key}", str(value), CACHE_TTL)


def force_scenario(name: str | None) -> None:
    """Pin the next mock orders to one scenario. Used by tests and demos."""
    global FORCE_SCENARIO
    if name is not None and name not in SCENARIO_WEIGHTS:
        raise ValueError(f"Unknown mock scenario: {name}")
    FORCE_SCENARIO = name


def fast_forward(provider_order_id: str, seconds: int) -> None:
    """Pretend `seconds` have passed for a mock order.

    Lets a test drive an order from created to code-received without sleeping.
    """
    state = cache.get(_key(provider_order_id))
    if state is None:
        return
    created_at = datetime.fromisoformat(state["created_at"])
    state["created_at"] = (created_at - timedelta(seconds=seconds)).isoformat()
    cache.set(_key(provider_order_id), state, CACHE_TTL)


# -- rental test helpers ----------------------------------------------------


def _rental_mode() -> str:
    return cache.get(f"{RENTAL_PREFIX}mode") or "OK"


def _set_rental_mode(mode: str | None) -> None:
    if mode is None:
        cache.delete(f"{RENTAL_PREFIX}mode")
    else:
        cache.set(f"{RENTAL_PREFIX}mode", mode, CACHE_TTL)


#: OK          rented at once; a first message lands after a few seconds
#: QUIET       rented at once; no message arrives unless a test sends one
#: PENDING     the provider is still processing the purchase on the first read
#: TIMEOUT     the purchase goes through but its answer is lost (once)
#: REFUSE      the provider refuses the purchase (or an extension)
#: NO_STOCK    no number in stock
#: PROVIDER_ERR pricing calls fail
RENTAL_MODES = {"OK", "QUIET", "PENDING", "TIMEOUT", "REFUSE", "NO_STOCK", "PROVIDER_ERR"}


def force_rental_mode(mode: str | None) -> None:
    if mode is not None and mode not in RENTAL_MODES:
        raise ValueError(f"Unknown mock rental mode: {mode}")
    _set_rental_mode(mode)


def set_rental_price(service_code: str, days: int, usd) -> None:
    """Make the mock quote `usd` for this rental (None restores the default)."""
    key = f"{RENTAL_PREFIX}price:{service_code}:{days}"
    if usd is None:
        cache.delete(key)
    else:
        cache.set(key, str(usd), CACHE_TTL)


def send_rental_sms(provider_rental_id: str, body: str, code: str = "",
                    sender: str = "12345") -> None:
    state = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
    if state is None:
        return
    state["messages"].insert(0, {
        "id": f"{provider_rental_id}-sms-{len(state['messages']) + 2}",
        "body": body, "code": code, "sender": sender, "at": timezone.now().isoformat(),
    })
    cache.set(f"{RENTAL_PREFIX}{provider_rental_id}", state, CACHE_TTL)


def end_rental_upstream(provider_rental_id: str, state: str = "EXPIRED") -> None:
    """Make the provider report this rental as EXPIRED or REFUNDED."""
    entry = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
    if entry is None:
        return
    entry["state"] = state
    if state == "EXPIRED":
        entry["ends_at"] = timezone.now().isoformat()
    cache.set(f"{RENTAL_PREFIX}{provider_rental_id}", entry, CACHE_TTL)


def block_rental_refund(provider_rental_id: str) -> None:
    entry = cache.get(f"{RENTAL_PREFIX}{provider_rental_id}")
    if entry is not None:
        entry["refundable"] = False
        cache.set(f"{RENTAL_PREFIX}{provider_rental_id}", entry, CACHE_TTL)
