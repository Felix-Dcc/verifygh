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
    #: False when the catalogue carries no stock (TextVerified's service list
    #: is prices only): the sync then leaves stock to apps/catalog/stock.py.
    reports_stock: bool = True


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
    #: Until when the number may be reused for another code, where the
    #: provider documents reuse. None otherwise.
    reusable_until: datetime | None = None
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


class RentalState(str, Enum):
    """A rented number's state upstream, normalised across providers."""

    #: Bought, but the provider has not handed over the number yet.
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"
    #: The provider says the purchase did not go through: nothing was rented.
    FAILED = "FAILED"
    #: A state the adapter does not recognise. Never acted on.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RentalDTO:
    """One rented number, as the provider sees it."""

    state: RentalState
    provider_rental_id: str = ""
    #: The provider's purchase record. Kept so a purchase the provider is still
    #: processing can be looked up again without buying twice.
    sale_id: str = ""
    phone_number: str = ""
    ends_at: datetime | None = None
    can_refund: bool = False
    refundable_until: datetime | None = None
    #: What the purchase cost us, in `currency`, when the provider says.
    cost: Decimal | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class RentalExtensionDTO:
    provider_extension_id: str
    new_ends_at: datetime | None = None
    cost: Decimal | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class RentalMessageDTO:
    """One SMS received on a rented number. Never logged."""

    provider_message_id: str
    body: str = ""
    code: str = ""
    sender: str = ""
    received_at: datetime | None = None


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
                     time_budget: float | None = None,
                     skip: set[str] | None = None) -> list[ProviderServiceDTO]:
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

    # -- reuse -------------------------------------------------------------

    #: Whether the provider documents reusing a finished verification's number
    #: for another code.
    supports_reuse: bool = False

    def reuse_order(self, provider_order_id: str, idempotency_key: str) -> ProviderOrderDTO:
        """Ask for another code on the number of a finished verification.

        Returns the new reservation. Only adapters with a documented reuse call
        implement this.
        """
        raise NotImplementedError(f"{self.display_name} documents no number reuse.")

    #: Whether the provider documents reactivating a finished verification
    #: once its reuse window has closed (TextVerified's "Reactivate").
    supports_reactivation: bool = False

    def can_reactivate(self, provider_order_id: str) -> bool:
        """Whether the provider says this verification can be reactivated now."""
        return False

    def reactivate_order(self, provider_order_id: str,
                         idempotency_key: str) -> ProviderOrderDTO:
        """Reactivate a finished verification for another code on its number."""
        raise NotImplementedError(f"{self.display_name} documents no reactivation.")

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

    #: Whether the provider reviews reported verifications and shows its refund
    #: on the verification itself - so a customer's refund can wait for, and
    #: follow, the provider's own decision.
    tracks_report_refunds: bool = False

    def report_outcome(self, provider_order_id: str) -> str | None:
        """The provider's decision on a reported verification.

        "REFUNDED" once it has refunded us, "PENDING" while it has not; None
        where the provider cannot say. A refusal arrives through the provider's
        support, not here, so it is never inferred from silence.
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

    # -- rentals -----------------------------------------------------------

    #: Whether the provider documents renting a number for days at a time.
    supports_rentals: bool = False

    def rental_price(self, service_code: str, days: int) -> Decimal | None:
        """What renting `service_code` for `days` days costs us, or None when
        the provider does not offer that combination."""
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def rental_stock(self, service_code: str, days: int) -> int:
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def create_rental(self, service_code: str, days: int,
                      idempotency_key: str) -> RentalDTO:
        """Rent a number. Safe to call again with the same key after an unclear
        failure: the provider answers with the same purchase."""
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def get_rental(self, provider_rental_id: str) -> RentalDTO:
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def get_rental_sale(self, sale_id: str) -> RentalDTO:
        """Follow up a purchase the provider was still processing."""
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def refund_rental(self, provider_rental_id: str) -> bool:
        """Ask for the rental to be refunded; False when the provider refuses."""
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def extend_rental(self, provider_rental_id: str, days: int) -> RentalExtensionDTO:
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

    def rental_messages(self, provider_rental_id: str) -> list[RentalMessageDTO]:
        raise NotImplementedError(f"{self.display_name} documents no rentals.")

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
