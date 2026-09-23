"""Hubtel Mobile Money adapter - structure complete, endpoints intentionally blank.

READ THIS BEFORE FILLING IT IN
------------------------------
Hubtel's API reference is published behind a merchant account on their
developer portal. It was not reachable when this file was written, so every
endpoint, field name and callback detail below is left blank and marked
`TODO(credentials)`.

They are deliberately **not guessed**. A plausible-looking URL produces code
that reads as finished, passes review, and then fails against the real API -
or worse, half-works and leaves money in a state nobody can reconcile. The
community wrappers on GitHub are not a substitute for the official reference:
they are unversioned, unofficial, and often years stale.

WHAT TO FILL IN, FROM THE OFFICIAL DOCUMENTATION
------------------------------------------------
1. `BASE_URL` and `PATH_RECEIVE_MONEY` - the direct mobile money charge that
   sends the approval prompt to the customer's phone.
2. `PATH_TRANSACTION_STATUS` - the authoritative status lookup. This one is
   not optional here: see "Callback authenticity" below.
3. `AUTH_SCHEME` - how requests authenticate (Basic with client id/secret, a
   bearer token, or something else) and whether the merchant account number is
   part of the path or the body.
4. `NETWORK_CHANNELS` - the exact channel strings for MTN, Telecel and
   AirtelTigo. These change when networks rebrand; Telecel was Vodafone.
5. `STATUS_MAP` - every status value the API and the callback can return,
   mapped onto ChargeStatus. An unmapped value must never read as SUCCESS.
6. `CALLBACK_*` - the callback body's field names, and the answer to the
   question below.

CALLBACK AUTHENTICITY - THE DECISION THAT MATTERS
-------------------------------------------------
Before going live, establish from the documentation whether Hubtel signs its
callbacks (an HMAC header over the raw body, as Paystack does) or not.

* **If it signs them:** implement `verify_webhook` with a constant-time compare
  over the raw bytes, exactly as `paystack.py` does.
* **If it does not:** an unauthenticated callback is a stranger's HTTP request.
  It must never credit a wallet on its own. In that case `verify_webhook`
  stays False and the callback is treated only as a *hint* to re-check the
  transaction with `fetch_charge`, whose answer is authoritative. That path is
  already built: `reconcile_payment` in `apps/payments/services.py` credits
  only on what the provider tells us directly, and the reconciliation task
  already runs every 15 minutes.

Until every constant here is filled in from the documentation, this adapter
reports itself unconfigured, refuses to start a charge, and production refuses
to boot with `PAYMENT_PROVIDER=hubtel`.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import requests
from django.conf import settings

from apps.accounts.constants import MomoNetwork
from apps.common.errors import ProviderError, ServiceUnavailable
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

logger = logging.getLogger("verifygh.payments.hubtel")

REQUEST_TIMEOUT = 30


class _NotConfigured(ServiceUnavailable):
    code = "PAYMENT_PROVIDER_NOT_CONFIGURED"
    message = "Mobile Money payments are not available right now."


class HubtelProvider(PaymentProvider):
    key = "hubtel"
    display_name = "Hubtel Mobile Money"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)

    # ------------------------------------------------------------------
    # TODO(credentials): fill in from Hubtel's official API reference.
    # Leave as empty strings until the documentation is in front of you.
    # ------------------------------------------------------------------
    BASE_URL = ""                  # API host
    PATH_RECEIVE_MONEY = ""        # direct mobile money charge (sends the prompt)
    PATH_TRANSACTION_STATUS = ""   # authoritative status lookup

    #: "basic" | "bearer" | ... - how the documented requests authenticate.
    AUTH_SCHEME = ""

    #: MomoNetwork -> the channel string Hubtel expects.
    NETWORK_CHANNELS: dict[str, str] = {}

    #: Hubtel status value -> ChargeStatus. Anything unlisted is treated as
    #: PROCESSING: an unknown status must never be read as money received.
    STATUS_MAP: dict[str, ChargeStatus] = {}

    #: Callback body field names, once known.
    CALLBACK_REFERENCE_FIELD = ""
    CALLBACK_STATUS_FIELD = ""
    CALLBACK_AMOUNT_FIELD = ""
    CALLBACK_TRANSACTION_ID_FIELD = ""

    #: True only when the documentation confirms Hubtel signs its callbacks
    #: and `verify_webhook` below implements that signature check.
    CALLBACKS_ARE_SIGNED = False

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        credentials = settings.PAYMENT_CREDENTIALS.get("hubtel", {})
        self.client_id = credentials.get("client_id", "")
        self.client_secret = credentials.get("client_secret", "")
        self.merchant_account = credentials.get("merchant_account", "")
        self.base_url = str(credentials.get("base_url", "") or self.BASE_URL).rstrip("/")
        self._session = requests.Session()

    @property
    def is_implemented(self) -> bool:
        """True once the endpoints have been filled in from the documentation."""
        return bool(self.BASE_URL and self.PATH_RECEIVE_MONEY and self.PATH_TRANSACTION_STATUS)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.is_implemented
            and self.client_id
            and self.client_secret
            and self.merchant_account
        )

    def _require_configured(self, what: str) -> None:
        if not self.is_configured:
            logger.error(
                "hubtel_not_configured",
                extra={"operation": what, "implemented": self.is_implemented},
            )
            raise _NotConfigured()

    def _require_path(self, path: str, what: str) -> str:
        if not path:
            # Reached only if someone fills in some constants but not others.
            logger.error("hubtel_path_missing", extra={"operation": what})
            raise _NotConfigured()
        return f"{self.base_url}{path}"

    # -- charges ---------------------------------------------------------

    def initiate_charge(self, *, amount: Decimal, currency: str, phone: str, network: str,
                        reference: str, email: str = "",
                        metadata: dict | None = None) -> ChargeDTO:
        """Send the Mobile Money approval prompt to the customer's phone.

        TODO(credentials): build the documented request body and map the
        documented response onto ChargeDTO. Until then this raises, so a
        deposit fails cleanly and visibly instead of appearing to work.
        """
        self._require_configured("initiate_charge")
        channel = self.NETWORK_CHANNELS.get(network)
        if channel is None:
            raise ProviderError("That mobile money network is not supported yet.")
        self._require_path(self.PATH_RECEIVE_MONEY, "initiate_charge")
        raise _NotConfigured()

    def fetch_charge(self, reference: str) -> ChargeDTO:
        """Ask Hubtel what actually happened to a charge.

        This is the authoritative path - the one `reconcile_payment` uses, and
        the one that must carry the whole weight if callbacks turn out to be
        unsigned.

        TODO(credentials): call the documented status endpoint and map its
        response onto ChargeDTO via STATUS_MAP.
        """
        self._require_configured("fetch_charge")
        self._require_path(self.PATH_TRANSACTION_STATUS, "fetch_charge")
        raise _NotConfigured()

    # -- webhooks --------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        """Is this callback genuinely from Hubtel?

        False until the documentation says how to prove it. Returning False
        means `process_webhook` records the attempt and answers 401 without
        touching a wallet, which is the right behaviour for an unproven
        request - and stays right if Hubtel never signs callbacks at all.

        TODO(credentials): if callbacks are signed, implement the documented
        HMAC over `raw_body` with `hmac.compare_digest`, and set
        CALLBACKS_ARE_SIGNED = True. Never compare re-serialised JSON: key
        order and whitespace change, and a forged body would verify.
        """
        if not self.CALLBACKS_ARE_SIGNED:
            logger.warning("hubtel_webhook_unverifiable", extra={"bytes": len(raw_body)})
            return False
        raise _NotConfigured()

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        """TODO(credentials): map the documented callback body onto WebhookEventDTO.

        `event_id` must be stable per event (Hubtel's transaction id, or a
        deterministic `derive(...)` of the payload) so a replayed callback
        loses to the unique index instead of crediting twice.
        """
        raise _NotConfigured()

    def health_check(self) -> bool:
        return self.is_configured
