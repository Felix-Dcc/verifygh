"""The payment provider interface.

Ghana's MoMo aggregators (Paystack, Hubtel, Flutterwave, the MNO APIs) all do
the same four things, with different field names. This ABC is those four things.

The single most important rule in this file: **the client never tells us a
payment succeeded.** `initiate_charge` starts a charge; the only thing that can
move a payment to SUCCESS is a verified provider webhook, or our own outbound
`fetch_charge` call. A browser saying "it worked" means nothing.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    #: The provider is waiting for a one-time code that WE must submit on the
    #: customer's behalf. Distinct from PROCESSING because it is not a waiting
    #: state at all - nothing happens until we send the code, and collapsing the
    #: two is how a customer ends up staring at "waiting for confirmation" while
    #: holding an SMS code with nowhere to type it.
    OTP_REQUIRED = "OTP_REQUIRED"
    #: The customer must approve on their handset. We genuinely do wait here,
    #: and there is nothing for them to type into our UI.
    PHONE_AUTH_REQUIRED = "PHONE_AUTH_REQUIRED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ChargeDTO:
    """The provider's view of a charge."""

    provider_reference: str
    status: ChargeStatus
    amount: Decimal | None = None
    currency: str = "GHS"
    #: Shown to the user, e.g. "Approve the prompt on your phone, or dial *170#".
    instructions: str = ""
    #: Only used by providers that need a hosted page; MoMo prompts do not.
    redirect_url: str = ""
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEventDTO:
    """A normalised provider callback.

    `event_id` must be stable and unique per event - it is the idempotency key
    that stops a replayed webhook crediting a wallet twice. If a provider does
    not supply one, derive it deterministically from the payload (see
    `apps.common.idempotency.derive`), never randomly.
    """

    event_id: str
    event_type: str
    reference: str
    status: ChargeStatus
    provider_reference: str = ""
    amount: Decimal | None = None
    currency: str = "GHS"
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentProvider(abc.ABC):
    key: str = "base"
    display_name: str = "Base payment provider"

    #: Networks this provider can collect from, as MomoNetwork values.
    supported_networks: tuple[str, ...] = ()

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def submit_otp(self, *, reference: str, otp: str) -> "ChargeDTO":
        """Send a one-time code the customer gave us to the provider.

        Only meaningful for providers whose flow can stop at OTP_REQUIRED. The
        default refuses, so a provider that never asks for one cannot be handed
        a code by mistake.
        """
        from apps.common.errors import ProviderError

        raise ProviderError("This payment method does not use a one-time code.")

    @abc.abstractmethod
    def initiate_charge(
        self,
        *,
        amount: Decimal,
        currency: str,
        phone: str,
        network: str,
        reference: str,
        email: str = "",
        metadata: dict | None = None,
    ) -> ChargeDTO:
        """Ask the provider to collect `amount` from `phone`.

        `reference` is *our* reference and must be echoed back in the webhook.
        """

    @abc.abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        # `headers` always arrives with lowercase keys (see WebhookView).
        """Verify the callback's signature against the raw, unparsed body.

        Must use a constant-time comparison, and must hash the exact bytes
        received - re-serialising parsed JSON changes whitespace and key order
        and will produce a different digest.
        """

    @abc.abstractmethod
    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        """Normalise a verified callback. Only called after `verify_webhook`."""

    def parse_webhook_payload(self, payload: dict) -> WebhookEventDTO:
        """Rebuild an event from a payload we stored earlier.

        Used to finish applying a callback that was recorded but failed to
        apply - the signature was already verified when it arrived, so there is
        nothing left to verify, only to normalise.

        The default re-serialises and reuses `parse_webhook`, which is correct
        for any adapter whose parsing depends only on the body.
        """
        import json

        return self.parse_webhook(json.dumps(payload).encode("utf-8"), {})

    @abc.abstractmethod
    def fetch_charge(self, reference: str) -> ChargeDTO:
        """Ask the provider directly about a charge.

        Used for reconciliation when a webhook is late or never arrives - the
        safety net that stops a user's money going missing because of a dropped
        callback.
        """

    def health_check(self) -> bool:
        return True
