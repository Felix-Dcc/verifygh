"""The verification provider interface.

Everything the application knows about sourcing numbers goes through this ABC.
Concrete adapters translate between our vocabulary and a provider's, and nothing
outside `apps/verification/` ever sees a provider-specific field name.

Rules every adapter must follow:

* Use the provider's **official API** only. No scraping, no browser automation,
  no working around authentication, CAPTCHAs, rate limits or payment controls.
* Never invent an endpoint. If the documentation is not in hand, leave the
  constant as `TODO(credentials)` and let the mock provider carry development.
* Raise `ProviderError` for anything the caller cannot fix. Provider internals
  (URLs, keys, raw error bodies) never reach the user.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ProviderOrderState(str, Enum):
    """Provider-side states, normalised across providers.

    Our own `OrderStatus` is richer (it also covers wallet and refund state);
    this enum is only what the upstream provider can tell us.
    """

    PENDING = "PENDING"
    NUMBER_ASSIGNED = "NUMBER_ASSIGNED"
    WAITING_FOR_CODE = "WAITING_FOR_CODE"
    CODE_RECEIVED = "CODE_RECEIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProviderServiceDTO:
    code: str
    name: str
    country_code: str
    cost: Decimal
    currency: str = "USD"
    supports_sms: bool = True
    supports_voice: bool = False
    available: bool = True
    available_count: int | None = None
    ttl_minutes: int = 20


@dataclass(frozen=True)
class ProviderCountryDTO:
    code: str
    name: str
    dial_code: str = ""


@dataclass(frozen=True)
class AvailabilityDTO:
    available: bool
    count: int | None = None
    note: str = ""


@dataclass(frozen=True)
class CodeDTO:
    """A verification message from the provider.

    `code` is the extracted one-time code; `full_text` is the raw SMS body.
    Whether either may be shown to the end user is a contractual question,
    answered by `Provider.permits_code_display` plus the DISPLAY_VERIFICATION_CODES
    setting - never decided inside an adapter.
    """

    code: str
    full_text: str = ""
    received_at: datetime | None = None
    sender: str = ""


@dataclass(frozen=True)
class ProviderOrderDTO:
    provider_order_id: str
    state: ProviderOrderState
    phone_number: str = ""
    expires_at: datetime | None = None
    cost: Decimal | None = None
    currency: str = "USD"
    code: CodeDTO | None = None
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class VerificationProvider(abc.ABC):
    """Base class for every verification provider adapter."""

    key: str = "base"
    display_name: str = "Base provider"

    #: Whether this provider's agreement allows relaying the message body/code.
    permits_code_display: bool = True

    #: Whether the provider pushes updates to us. When False we poll politely.
    supports_webhooks: bool = False

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    # -- catalog ---------------------------------------------------------

    @abc.abstractmethod
    def get_services(self) -> list[ProviderServiceDTO]:
        """Every (service, country) offering the provider exposes to us."""

    @abc.abstractmethod
    def get_countries(self) -> list[ProviderCountryDTO]:
        """Countries the provider can source numbers from."""

    @abc.abstractmethod
    def get_pricing(self, service_code: str, country_code: str) -> Decimal:
        """Current provider cost, in the provider's own currency."""

    @abc.abstractmethod
    def get_availability(self, service_code: str, country_code: str) -> AvailabilityDTO:
        """Whether a number can be reserved right now."""

    # -- orders ----------------------------------------------------------

    @abc.abstractmethod
    def create_order(
        self, service_code: str, country_code: str, idempotency_key: str
    ) -> ProviderOrderDTO:
        """Reserve a number.

        `idempotency_key` must be forwarded to the provider when it supports one,
        so a retry after a network timeout does not reserve (and bill us for) two
        numbers.
        """

    @abc.abstractmethod
    def get_order_status(self, provider_order_id: str) -> ProviderOrderDTO:
        """Current upstream state of a reservation."""

    @abc.abstractmethod
    def get_verification_code(self, provider_order_id: str) -> CodeDTO | None:
        """The received code, or None if nothing has arrived yet."""

    @abc.abstractmethod
    def cancel_order(self, provider_order_id: str) -> bool:
        """Release a number early. Returns True when the provider accepted it."""

    @abc.abstractmethod
    def refund_order(self, provider_order_id: str) -> bool:
        """Ask the provider to refund a failed reservation, where its policy allows."""

    # -- health ----------------------------------------------------------

    def health_check(self) -> bool:
        """Cheap liveness probe. Adapters may override with a real call."""
        try:
            self.get_countries()
            return True
        except Exception:
            return False
