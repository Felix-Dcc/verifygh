# Payment integration

How to replace the mock MoMo provider with a real Ghanaian aggregator.

---

## Hubtel

The adapter exists at `backend/apps/payments/hubtel.py` with its structure
complete and **every endpoint deliberately blank**. Hubtel publishes its API
reference behind a merchant account, so the values were not available when it
was written, and guessing them would produce code that reads as finished and
fails in production.

While it is blank:

* `PAYMENT_PROVIDER=hubtel` **refuses to boot in production** - the guard names
  the reason rather than letting every deposit fail quietly;
* a deposit attempt raises `PAYMENT_PROVIDER_NOT_CONFIGURED`;
* a callback to `/api/v1/payments/webhooks/hubtel/` answers `401` and moves no
  money, whatever it claims;
* `tests/test_hubtel_safety.py` (10 tests) fails if anyone fills in an endpoint
  without the documentation, or forgets to update
  `apps/payments/implemented.py` when they do.

### What to bring back from the documentation

| Constant | What it needs |
|---|---|
| `BASE_URL`, `PATH_RECEIVE_MONEY` | The direct Mobile Money charge that sends the approval prompt |
| `PATH_TRANSACTION_STATUS` | The authoritative status lookup |
| `AUTH_SCHEME` | Basic with client id/secret, bearer, or otherwise - and where the merchant account number belongs |
| `NETWORK_CHANNELS` | The exact channel strings for MTN, Telecel and AirtelTigo (Telecel was Vodafone; confirm the current value) |
| `STATUS_MAP` | Every status the API and callback can return. Anything unmapped must read as PROCESSING, never SUCCESS |
| `CALLBACK_*` | The callback body's field names |

### The question that decides the design

**Does Hubtel sign its callbacks?**

* **Yes** - implement `verify_webhook` as an HMAC over the raw request bytes
  with a constant-time compare, exactly as `paystack.py` does. Never verify
  re-serialised JSON: whitespace and key order change, and a forged body would
  pass.
* **No** - then an unauthenticated callback is a stranger's HTTP request and
  must never credit a wallet by itself. Leave `verify_webhook` returning False
  and treat the callback purely as a hint to re-check the transaction with
  `fetch_charge`, whose answer is authoritative. That path already exists:
  `reconcile_payment` credits only on what the provider tells us directly, and
  the reconciliation task runs every 15 minutes.

Either way the rule from the rest of this document holds: the browser never
confirms a payment.

### Going live

1. Fill in the constants above, and add `"hubtel"` to
   `IMPLEMENTED_PAYMENT_PROVIDERS` in `apps/payments/implemented.py`.
2. Set `HUBTEL_CLIENT_ID`, `HUBTEL_CLIENT_SECRET`, `HUBTEL_MERCHANT_ACCOUNT`
   and `HUBTEL_BASE_URL`.
3. Register the callback URL with Hubtel:
   `https://<your-api-domain>/api/v1/payments/webhooks/hubtel/`, and restrict
   it to their published IP range at the edge if they publish one.
4. Run the webhook tests against a sandbox account before pointing real money
   at it.

---

## The interface

Every payment provider implements four methods (`apps/payments/base.py`):

```python
class PaymentProvider(ABC):
    key: str
    supported_networks: tuple[str, ...]

    def initiate_charge(self, *, amount, currency, phone, network,
                        reference, email="", metadata=None) -> ChargeDTO: ...
    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool: ...
    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO: ...
    def fetch_charge(self, reference: str) -> ChargeDTO: ...
```

That is the whole contract. `apps/wallet`, `apps/orders` and the entire API layer know
nothing about Paystack, Hubtel or MTN.

**`reference` is ours.** We generate `VGH-PAY-XXXXXXXX`, the provider echoes it in the
webhook, and it is the idempotency key for the ledger credit. Any provider you choose must
support passing a merchant reference through to the callback. If one does not, do not use
it — you would have no reliable way to tie a callback to a payment.

---

## What is shipped

| Adapter | `PAYMENT_PROVIDER` | State |
|---|---|---|
| `MockPaymentProvider` | `mock` | Complete. Signs webhooks with a real HMAC so the production verification path is what runs in tests. |
| `PaystackProvider` | `paystack` | Complete plumbing against Paystack's documented endpoints. Three values need confirming — see below. |

Hubtel, Flutterwave and a direct MNO integration are each one file.

---

## Paystack

Paystack is the default choice because it supports GHS mobile money collections directly.

### 1. Merchant account

Register at <https://paystack.com>, complete Ghanaian business verification, and enable
Mobile Money collections for GHS. Take your **secret key** (`sk_live_…`) from
Settings → API Keys & Webhooks. The public key is not used — we never collect card details
in the browser.

### 2. Environment

```bash
PAYMENT_PROVIDER=paystack
PAYSTACK_SECRET_KEY=sk_live_xxxxxxxxxxxx
PAYSTACK_BASE_URL=https://api.paystack.co
```

Use `sk_test_…` in staging. `config/settings/prod.py` refuses to boot with
`PAYMENT_PROVIDER=paystack` and no secret key, because a live provider without a webhook
secret would accept forged callbacks.

### 3. Register the webhook — **you must do this**

In the Paystack dashboard, Settings → API Keys & Webhooks → Webhook URL:

```
https://api.your-domain.com/api/v1/payments/webhooks/paystack/
```

Nothing works without this. Deposits will sit `PENDING` until reconciliation catches them.

Also restrict that path to Paystack's published IP range at your edge. Signature
verification is the real control; the allowlist is defence in depth.

### 4. Confirm three things — `TODO(credentials)`

The endpoints in `apps/payments/paystack.py` are the documented ones. Three values vary by
market and account, and are marked in the file:

1. **Mobile money provider codes.** Currently `mtn` / `vod` / `atl`. Telecel took over
   Vodafone Ghana, so confirm whether your account still expects `vod`.
   ```python
   NETWORK_CODES = { MomoNetwork.MTN: "mtn",
                     MomoNetwork.TELECEL: "vod",
                     MomoNetwork.AT: "atl" }
   ```
2. **Charge flow.** We use `POST /charge` with a `mobile_money` object. Some accounts are
   provisioned for the hosted transaction-initialise flow instead.
3. **Webhook events.** We act on `charge.success` and `charge.failed`. Confirm the full set
   your account emits.

### 5. Verify before launch

```bash
# Test keys, staging.
curl -X POST https://staging-api.your-domain.com/api/v1/payments/deposit/ \
  -H "Content-Type: application/json" -H "X-CSRF-Token: <token>" \
  --cookie "vgh_access=<token>" \
  -d '{"amount": "1.00", "phone": "024 123 4567"}'
```

Then check, in order:

- [ ] The prompt reaches the test handset.
- [ ] Approving it fires a webhook that returns `200`.
- [ ] The wallet is credited **once**.
- [ ] Re-sending the identical webhook returns `{"status": "duplicate"}` and does not credit again.
- [ ] A webhook with a corrupted body returns `401` and credits nothing.
- [ ] Declining the prompt marks the payment `FAILED` and credits nothing.
- [ ] `POST /payments/{ref}/refresh/` on a stuck payment recovers it.
- [ ] `python manage.py reconcile_wallets` exits `0`.

---

## Adding another provider

Four steps.

**1. Write the adapter** — `apps/payments/hubtel.py`:

```python
from apps.payments.base import ChargeDTO, ChargeStatus, PaymentProvider, WebhookEventDTO

class HubtelProvider(PaymentProvider):
    key = "hubtel"
    display_name = "Hubtel Mobile Money"
    supported_networks = (MomoNetwork.MTN, MomoNetwork.TELECEL, MomoNetwork.AT)

    def initiate_charge(self, *, amount, currency, phone, network, reference,
                        email="", metadata=None) -> ChargeDTO:
        ...

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        # Over the RAW bytes, constant-time compare. Never re-serialise.
        ...

    def parse_webhook(self, raw_body: bytes, headers: dict) -> WebhookEventDTO:
        # event_id must be stable and unique. If the provider does not supply one,
        # derive it deterministically with apps.common.idempotency.derive - never
        # randomly, or every replay looks like a new event.
        ...

    def fetch_charge(self, reference: str) -> ChargeDTO:
        ...
```

**2. Register it** — `apps/payments/registry.py`:

```python
_REGISTRY = { ..., HubtelProvider.key: HubtelProvider }
```

**3. Add credentials** — `config/settings/base.py` under `PAYMENT_CREDENTIALS`, and
`.env.example`.

**4. Switch** — `PAYMENT_PROVIDER=hubtel`. Nothing else changes.

### The rules an adapter must follow

* **Verify over raw bytes.** `request.body`, not a re-serialised dict.
* **Constant-time compare.** `hmac.compare_digest`.
* **Stable event ids.** A random id makes every replay look new and will double-credit.
* **A timeout is not a failure.** The charge may well have been created. Raise
  `ProviderError` and let reconciliation decide — never mark it failed.
* **Never leak provider internals.** Log the provider's message; show the user a generic one.
* **Money as `Decimal`.** Convert subunits explicitly (`to_subunit` / `from_subunit`).

---

## Switching providers with live balances

The ledger is provider-agnostic, so a switch is safe if you sequence it:

1. Deploy the new adapter with `PAYMENT_PROVIDER` still on the old one.
2. Register the new webhook URL; **keep the old one live**.
3. Switch `PAYMENT_PROVIDER` and restart.
4. Keep the old webhook accepting callbacks for at least 48 hours — in-flight payments
   will still call it. Both handlers write to the same ledger, keyed by reference, so
   there is no ambiguity.
5. Run `reconcile_recent_payments` over the switchover window.
6. Retire the old webhook once no `PENDING` payments reference it.

---

## Fees and pricing

The MoMo collection fee is absorbed into the customer price by the pricing engine
(`payment_fee_percent` on the pricing rule, default 2%). Set it to your aggregator's actual
rate. Users never see a separate charge — the price on the card is what leaves the wallet.

Because deposits are a wallet top-up rather than a per-order charge, one fee covers several
purchases. That is the main reason for the prepaid model.

---

## Withdrawals

Not implemented, deliberately. The ledger supports a `WITHDRAWAL` entry type and the
`PaymentDirection.PAYOUT` field exists, but no payout flow is wired up.

Before building one, note that paying money out is a materially different regulatory
position from collecting it, and will require AML checks, payout limits, a reversal path
and almost certainly a conversation with the Bank of Ghana. Today, a balance is returned
only on account closure, through the channel it arrived on.
