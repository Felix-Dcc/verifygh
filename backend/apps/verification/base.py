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


@dataclass(frozen=True)
class BalanceDTO:
    """Our own account balance with a provider, in the provider's currency.

    `available` is what can be spent now. `frozen` is held against numbers
    already reserved: OnlineSim charges it only if an SMS arrives and returns
    it otherwise, so it is neither spendable nor spent.
    """

    available: Decimal
    frozen: Decimal = Decimal("0")
    currency: str = "USD"


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

    @property
    def is_configured(self) -> bool:
        """Whether the credentials this adapter needs are present.

        Adapters with credentials override this. It answers "could we call the
        provider", never "is the provider up" - that is `health_check`.
        """
        return True

    # -- catalog ---------------------------------------------------------

    @abc.abstractmethod
    def get_services(self, *, priority: list[str] | None = None,
                     time_budget: float | None = None) -> list[ProviderServiceDTO]:
        """Every (service, country) offering the provider exposes to us.

        Adapters whose catalogue is priced one call at a time may return only
        part of it per sync: `priority` names service codes to price first
        (case-insensitive), and `time_budget` caps the seconds spent. Adapters
        that get the whole catalogue in one go ignore both.
        """

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

    # -- number quality ----------------------------------------------------

    #: Whether the provider documents a way to report a number that did not
    #: work (for example, one a service says is already registered).
    supports_issue_reports: bool = False

    def report_number_issue(self, provider_order_id: str, reason: str) -> bool | None:
        """Tell the provider a number was unusable. None when it has no way to hear it.

        True/False is whether the provider accepted the report. Adapters
        override this only with an endpoint their documentation actually has.
        """
        return None

    def check_number_reuse(self, provider_order_id: str, service_code: str) -> bool | None:
        """Whether the provider says this number was used for this service before.

        None means "unknown", and it is the only honest answer today: neither
        OnlineSim nor TextVerified documents any history or reuse lookup. It
        stays in the interface so an adapter can answer if a provider ever
        publishes one - and so nobody mistakes the absence for "fresh".
        """
        return None

    def release_retry_after_seconds(self, service_code: str) -> int:
        """How long to wait before retrying a release the provider refused."""
        return 60

    # -- our account with the provider ------------------------------------

    #: Whether the provider documents a way to read our account balance.
    supports_balance: bool = False

    #: Whether the provider documents a way to add money to our account through
    #: its API. No provider we use does: OnlineSim is funded by hand through its
    #: website (see docs/PROVIDER-FUNDING.md). Nothing may set this to True
    #: without a documented endpoint and written permission from the provider.
    supports_account_funding: bool = False

    def get_balance(self) -> BalanceDTO | None:
        """Our balance with the provider, or None when it has no way to tell us.

        Raises ProviderError when the provider documents a balance call and the
        call fails, so the caller can tell "unknown" apart from "unsupported".
        """
        return None

    def fund_account(self, amount: Decimal, currency: str, reference: str):
        """Add money to our provider account through the provider's API.

        Deliberately unimplemented everywhere: no provider we use offers it.
        Customer wallet money must never be routed here in any case - funding a
        provider is an operating expense, recorded in apps/funding.
        """
        raise NotImplementedError(
            f"{self.display_name} documents no API for funding our account."
        )

    # -- push notifications ------------------------------------------------

    @property
    def accepts_webhooks(self) -> bool:
        """Whether a signed callback from this provider can be verified now.

        False unless the provider documents a signature scheme *and* its secret
        is configured. An unsigned or unverifiable callback is never acted on.
        """
        return False

    def parse_webhook(self, raw_body: bytes, headers: dict) -> list[str] | None:
        """Verify a callback and return the provider order ids it concerns.

        None means the signature did not verify. The ids are only a hint to
        look now: the order is then read back through the authenticated API,
        so nothing in a callback body is ever trusted as the code itself.
        """
        return None

    # -- health ----------------------------------------------------------

    def health_check(self) -> bool:
        """Cheap liveness probe. Adapters may override with a real call."""
        try:
            self.get_countries()
            return True
        except Exception:
            return False
