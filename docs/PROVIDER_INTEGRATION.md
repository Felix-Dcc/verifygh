# Verification provider integration

How to replace the mock provider with a real, authorised upstream.

---

## TextVerified

The adapter is **implemented** against TextVerified's published OpenAPI v2
specification: `https://backend.textverified.com/swagger/v2/swagger.json`,
rendered at `https://www.textverified.com/docs/api/v2`.

A copy of the documented paths and states lives at
`backend/apps/verification/textverified_endpoints.json`, and
`tests/test_provider_safety.py` checks every endpoint the adapter calls, and
every provider state it maps, against that file. An invented or mistyped path
fails the suite.

### What it uses

| Purpose | Endpoint |
|---|---|
| Authenticate | `POST /api/pub/v2/auth` (headers `X-API-USERNAME`, `X-API-KEY`) |
| Service list | `GET /api/pub/v2/services` |
| Price | `POST /api/pub/v2/pricing/verifications` |
| Availability | `POST /api/pub/v2/inventory/verifications` |
| Reserve a number | `POST /api/pub/v2/verifications` |
| Verification details | `GET /api/pub/v2/verifications/{id}` |
| Messages | `GET /api/pub/v2/sms` |
| Cancel | `POST /api/pub/v2/verifications/{id}/cancel` |
| Report (their refund path) | `POST /api/pub/v2/verifications/{id}/report` |
| Balance | `GET /api/pub/v2/account/me` |

### Decisions worth knowing

**The bearer token is cached** in the shared cache until shortly before it
expires. Re-authenticating on every call would waste the rate limit for
nothing.

**`maxPrice` is always sent.** The adapter prices the service, then reserves
with a 5% tolerance (`PROVIDER_PRICE_TOLERANCE`). Without it, an upstream price
move between the customer's quote and the reservation would be billed to us
silently. If the price has moved further, the provider refuses and the order
fails - which refunds the customer.

**`Idempotency-Key` is forwarded** on reservation, so a retry after a network
timeout cannot reserve, and bill us for, two numbers.

**An unknown state is never "finished".** Anything outside the documented enum
maps to PENDING and is settled by the expiry sweep, so a new upstream state
cannot make an unfinished order look delivered.

**A service that cannot be priced is left out of the catalogue** rather than
listed at a guessed cost.

**The catalogue is US numbers.** The v2 verification API has no country list -
only area codes within the US - so `get_countries` reports exactly that.

### Testing without spending anything

TextVerified documents mock service names and fixed mock ids that create no
real numbers and no billing events. `tests/test_textverified_live.py` uses
them and skips unless credentials are present:

```bash
TEXTVERIFIED_API_KEY=... TEXTVERIFIED_API_USERNAME=you@example.com \
    pytest tests/test_textverified_live.py -v
```

It covers the documented cases: `test_success201` (completes with code
123456), `test_pending201`, `test_timeout201`, `test_no_numbers` and
`test_insufficient_balance`, plus the fixed ids `mock_ver_success` and
`mock_ver_cancelled`.

### ⚠️ Authorisation is still outstanding

TextVerified's terms prohibit sharing numbers with third parties. Reselling
access - what this platform does - needs an explicit reseller or partner
arrangement with them, **in writing**.

Having their API documented is not the same as being permitted to resell it.
Until that permission exists:

* keep `VERIFICATION_PROVIDER` unset or pointed at a provider you are
  authorised to resell;
* remember that an account terminated mid-trading fails every in-flight order
  at once. The refunds would be correct, but the supply would be gone.

---

## Read this first

VerifyGH resells access to someone else's service. That is only legitimate under an
arrangement that permits it.

**Before writing a line of adapter code, obtain:**

1. An account with the provider that **explicitly permits reselling**, or a reseller /
   partner agreement. A standard end-user account almost never does.
2. Their **official API documentation**.
3. Written confirmation of whether you may **relay message contents or verification codes
   to your end users**. Some agreements permit delivery status only.

**What this codebase will not do, and what you must not add:**

* No scraping of any page.
* No browser automation or headless-browser login.
* No working around authentication, CAPTCHAs, rate limits or payment controls.
* No retrying through a `429`.
* No sharing or reselling credentials.

These are not stylistic preferences. Circumventing a provider's technical controls breaches
their terms, will get the account terminated, and exposes the business to liability. The
adapter layer is built so the honest path is also the easy one.

---

## The interface

`apps/verification/base.py`:

```python
class VerificationProvider(ABC):
    key: str
    permits_code_display: bool      # from your agreement, not assumed
    supports_webhooks: bool

    def get_services(self) -> list[ProviderServiceDTO]: ...
    def get_countries(self) -> list[ProviderCountryDTO]: ...
    def get_pricing(self, service_code, country_code) -> Decimal: ...
    def get_availability(self, service_code, country_code) -> AvailabilityDTO: ...
    def create_order(self, service_code, country_code, idempotency_key) -> ProviderOrderDTO: ...
    def get_order_status(self, provider_order_id) -> ProviderOrderDTO: ...
    def get_verification_code(self, provider_order_id) -> CodeDTO | None: ...
    def cancel_order(self, provider_order_id) -> bool: ...
    def refund_order(self, provider_order_id) -> bool: ...
```

Provider states are normalised to `ProviderOrderState`, so nothing outside
`apps/verification/` ever sees a provider's own vocabulary.

An incomplete adapter fails at instantiation, not in production — `tests/test_catalog.py`
asserts that.

---

## What is shipped

| Adapter | `VERIFICATION_PROVIDER` | State |
|---|---|---|
| `MockVerificationProvider` | `mock` | Complete. Drives the entire product with no credentials. |
| `TextVerifiedProvider` | `textverified` | Structure complete, **endpoints intentionally blank**. |

### Why the endpoints are blank

`apps/verification/textverified.py` ships with:

```python
BASE_URL = ""
PATH_SERVICES = ""
PATH_CREATE_ORDER = ""
STATE_MAP: dict[str, ProviderOrderState] = {}
```

Guessing an endpoint produces code that looks finished and fails in production against an
API you are paying for. A blank constant raises a clear `PROVIDER_NOT_CONFIGURED` error,
and `is_configured` is `False`, so the platform keeps running on the mock instead of
failing in a confusing way.

Everything around them — HTTP session, auth header, timeouts, `429` backoff, error mapping,
credential redaction, rate limiting — is written and tested.

---

## Filling it in

### 1. Environment

```bash
VERIFICATION_PROVIDER=textverified
TEXTVERIFIED_API_KEY=...
TEXTVERIFIED_API_USERNAME=...
TEXTVERIFIED_BASE_URL=https://...      # from the documentation
```

### 2. Endpoints

From the official docs, fill each constant:

```python
BASE_URL          = "https://..."
PATH_TOKEN        = "/..."     # if the API issues a bearer token
PATH_SERVICES     = "/..."
PATH_COUNTRIES    = "/..."
PATH_PRICING      = "/..."
PATH_AVAILABILITY = "/..."
PATH_CREATE_ORDER = "/..."
PATH_ORDER_STATUS = "/{id}"    # formatted with the provider order id
PATH_ORDER_CANCEL = "/{id}/..."
PATH_ORDER_REFUND = "/{id}/..."
```

### 3. Authentication

`_headers()` supports both a bearer token from `PATH_TOKEN` and a raw API key. Confirm
which your account uses, and implement the token exchange in `_headers` if needed —
including refresh before expiry.

### 4. State mapping

```python
STATE_MAP = {
    "pending":   ProviderOrderState.PENDING,
    "assigned":  ProviderOrderState.NUMBER_ASSIGNED,
    "waiting":   ProviderOrderState.WAITING_FOR_CODE,
    "completed": ProviderOrderState.CODE_RECEIVED,
    "cancelled": ProviderOrderState.CANCELLED,
    "expired":   ProviderOrderState.EXPIRED,
    "failed":    ProviderOrderState.FAILED,
}
```

Use the **exact strings the API returns**. An unmapped state raises rather than guessing —
guessing here means telling a customer their order failed when it succeeded.

### 5. Response parsing

Implement `_parse_services`, `_parse_countries`, `get_pricing`, `get_availability`,
`create_order` and `get_order_status` to map documented fields onto the DTOs. Each raises
`_NotConfigured` until you do.

### 6. Idempotency

`create_order` receives `idempotency_key` (`vgh:<order-uuid>`, deterministic). If the API
supports an idempotency header, forward it — a retry after a network timeout must not
reserve and bill you for two numbers. **If it does not**, remove the retry from
`fulfil_order_task` and reconcile duplicates instead; retrying blind against an API without
idempotency will cost you money.

### 7. Code display

Set `permits_code_display` from your agreement, and the matching flag on the `Provider` row
in the admin console. When `False`, the UI shows delivery status and explains why, rather
than an empty box.

---

## Testing a real provider

Use a sandbox key if one exists, and the smallest possible order if not.

```bash
python manage.py sync_catalog --provider textverified
```

Then work through:

- [ ] `sync_catalog` populates services, countries, costs and availability
- [ ] The marketplace shows sensible prices (check the margin column in the admin console)
- [ ] A purchase reserves a number and the order reaches `NUMBER_ASSIGNED`
- [ ] The number receives a real SMS
- [ ] The code appears (if permitted) and `CODE_RECEIVED` is reached
- [ ] Cancelling before a code arrives is accepted and refunds the wallet
- [ ] Cancelling after a code arrives is **refused**
- [ ] An order left to expire refunds automatically
- [ ] `python manage.py reconcile_wallets` exits `0`
- [ ] The admin health page shows the provider as live, not mock

---

## Adding a different provider

```python
# apps/verification/smshub.py
from apps.verification.base import VerificationProvider
from apps.verification.registry import register

@register
class SmsHubProvider(VerificationProvider):
    key = "smshub"
    display_name = "SMS Hub"
    permits_code_display = True
    ...
```

Then `VERIFICATION_PROVIDER=smshub` and `python manage.py sync_catalog`. The `Provider` row
is created automatically on first sync.

Nothing in `apps/orders`, `apps/wallet` or the API changes.

---

## Running several providers

The data model already supports it: `ProviderService` is unique on
`(provider, service, country)`, and `resolve_offering` picks by `provider__priority` then
cost, so the cheapest working provider wins automatically.

To enable it:

1. Sync each provider — `sync_catalog --provider <key>`.
2. Set `priority` on each `Provider` row (lower wins).
3. Enable both.

To add failover on top, extend `fulfil_order` so a `NO_STOCK` or `PROVIDER_ERR` result
tries the next provider before failing the order. The order already stores
`provider_order_id` and `provider`, so a retry against a different provider is
representable without a schema change. That is left out deliberately — it is only worth the
complexity once you have two live providers.

---

## Cost and margin

`ProviderService.cost_amount` is the provider's price in their currency (normally USD), set
by `sync_catalog` and never typed in by hand in production. The pricing engine converts it,
applies markup, fees and buffer, and freezes the result onto the order.

Watch the margin column in Admin → Catalog. A negative margin means the provider's cost rose
past your floor price, and the answer is a pricing-rule change, not a code change.
