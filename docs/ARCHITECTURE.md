# VerifyGH — Architecture

> **VerifyGH** is a Ghana-focused payment and access layer for **supported, authorized**
> phone-verification services. Users top up a wallet with Mobile Money (GHS) and spend
> that balance on verification numbers sourced from an **authorized upstream provider API**.

---

## 1. Design principles

| Principle | How it is enforced |
|---|---|
| **The backend is authoritative** | Prices, balances, order state and payment state are *never* accepted from the client. Every write re-derives them server-side. |
| **Money is a ledger, not a number** | `Wallet.balance` is a cached projection. The truth is the append-only `WalletLedgerEntry` table. A management command re-derives balances and fails loudly on drift. |
| **Every external integration is an interface** | `PaymentProvider` and `VerificationProvider` are ABCs. Concrete adapters are registered in a registry and selected by env var. Swapping Paystack to Hubtel is a config change. |
| **Idempotency everywhere money moves** | Webhooks, order creation and refunds all carry idempotency keys backed by DB unique constraints — not by application-level "check then act". |
| **No provider ToS circumvention** | Only official APIs. No scraping, no browser automation, no CAPTCHA solving, no rate-limit evasion. The adapter layer has a hard rate limiter in front of it. |
| **Compliance is a feature** | Acceptable Use Policy acceptance is a DB-enforced precondition of purchase. Abuse signals are recorded, scored and actionable by admins. |

---

## 2. System context

```
                       +------------------------------+
   Ghanaian user       |        VerifyGH              |        Authorized
   (mobile browser)    |                              |        upstream provider
        |              |  Next.js (Vercel)            |        (e.g. TextVerified,
        |   HTTPS      |        | REST /api/v1        |         via official API)
        +-------------)|        v                     |              ^
                       |  Django + DRF (Render)       |--------------+
   MoMo (MTN /         |        |                     |   getServices / createOrder
   Telecel /       (---|        +-- PostgreSQL        |   getOrderStatus / cancel
   AirtelTigo)         |        +-- Redis             |
        |              |        +-- Celery workers    |
        |  webhook     |                              |
        +-------------)|  /api/v1/payments/webhook/   |
                       +------------------------------+
```

Money flow: **MoMo -> VerifyGH wallet (GHS ledger) -> order -> provider (USD cost)**.

The USD-to-GHS conversion, markup and fees are computed by the **pricing engine** at
quote time and *frozen onto the order*, so a mid-flight rate change cannot alter a
price the user already saw.

---

## 3. Backend module map

```
backend/
  config/            settings (base/dev/prod), urls, celery, asgi/wsgi
  apps/
    common/          base models, errors, pagination, idempotency, money, throttles
    accounts/        User, roles, email verification, sessions, AUP acceptance
    audit/           AuditLog, AdminAction, SuspiciousActivity
    wallet/          Wallet (cash + promotional buckets), WalletLedgerEntry,
                     ledger service (the only writer of either balance)
    payments/        Payment, PaymentWebhookEvent, provider interface + adapters
    catalog/         Country, Service, Provider, ProviderService, ExchangeRate
    pricing/         PricingRule, quote engine
    verification/    VerificationProvider interface + Mock/TextVerified adapters
    orders/          Order, OrderEvent, Refund, order state machine, Celery tasks
    notifications/   Notification model, channel abstraction (email now, SMS later)
    referrals/       ReferralCode, Referral, ReferralReward, ReferralRiskFlag,
                     eligibility policy and the idempotent reward
    adminapi/        admin-only endpoints, dashboards, RBAC
```

### Dependency direction (no cycles)

```
common  <--  accounts  <--  audit
   ^            ^
   |            |
catalog  <--  pricing
   ^            ^
   |            |
wallet   <--  orders  -->  verification
   ^            |
   |            v
payments    notifications
```

`orders` is the only module that orchestrates across `wallet`, `pricing` and
`verification`. `wallet` never imports `orders`.

---

## 4. The money path (critical)

### 4.1 Deposit

```
1. POST /api/v1/payments/deposits/     {amount, phone, network}
2. Payment row created  status=PENDING, reference=VGH-PAY-xxxxx (unique)
3. PaymentProvider.initiate_charge()   -> provider prompts the user's phone
4. --- the client is now irrelevant ---
5. Provider POSTs webhook  ->  signature verified  ->  raw body stored in
   PaymentWebhookEvent (unique on (provider, event_id)) — duplicate = 200 no-op
6. Inside ONE transaction:
     SELECT ... FOR UPDATE on wallet
     assert payment.status != SUCCESS      (idempotency guard #2)
     payment.status = SUCCESS
     ledger.credit(wallet, amount, DEPOSIT, idempotency_key=payment.reference)
     wallet.balance = <recomputed>
   COMMIT
7. Notification queued (outside the transaction, via transaction.on_commit)
```

Five identical webhooks produce **one** credit. Guaranteed by two independent
mechanisms: the `PaymentWebhookEvent` unique index and the
`WalletLedgerEntry.idempotency_key` unique index.

### 4.2 Purchase

```
1. POST /api/v1/orders/  {service, country, idempotency_key}
2. Server re-prices from the catalog (any client-supplied price is ignored)
3. Inside ONE transaction:
     SELECT ... FOR UPDATE on wallet     <- serialises concurrent spends
     if balance < price: 409 INSUFFICIENT_FUNDS (nothing written)
     ledger.debit(...)  -> Order(status=PROCESSING)
   COMMIT
4. Celery: provider.create_order() -> NUMBER_ASSIGNED -> WAITING_FOR_CODE
5. Celery poll (backoff, rate-limited) -> CODE_RECEIVED -> COMPLETED
6. On provider failure / expiry-without-code -> automatic REFUND ledger entry
```

Two concurrent purchases against a ₵20 balance at a ₵15 price: the row lock forces
them to serialise, and the second sees ₵5 and is rejected. Covered by a test that
runs real threads against real DB connections.

### 4.3 Order state machine

```
CREATED -> PAYMENT_PENDING -> PROCESSING -> NUMBER_ASSIGNED -> WAITING_FOR_CODE
                                  |                                  |
                                  |                                  +-> CODE_RECEIVED -> COMPLETED
                                  |                                  +-> EXPIRED ---+
                                  +-> FAILED --------------------------------------+
                                  +-> CANCELLED -----------------------------------+
                                                                                   v
                                                                               REFUNDED
```

Transitions are validated by an explicit `ALLOWED_TRANSITIONS` map; an illegal
transition raises rather than silently writing. Every transition appends an
`OrderEvent` — that table *is* the user-visible timeline.

---

## 5. Pricing engine

```
provider_cost_usd                     from ProviderService (synced from provider API)
  x exchange_rate (USD->GHS)          from ExchangeRate (provider-agnostic source)
  = base_cost_ghs
  + markup                            PricingRule: PERCENTAGE | FIXED | HYBRID
  + payment_fee                       configurable %, covers the MoMo collection fee
  + risk_buffer                       covers refund/failure rate
  = raw_price
  -> rounded per PricingRule.rounding (NEAREST_0_10 / NEAREST_0_50 / NEAREST_1_00 / CEIL_1_00)
  -> clamped to [min_price, max_price]
  = customer_price_ghs
```

Rules resolve **most-specific-first**: service+country, then service, then the
global default. Nothing is hardcoded; the exchange rate lives behind an
`ExchangeRateProvider` interface (manual admin entry in dev, API-backed in prod)
and every quote records which rate row it used.

---

## 6. Provider abstraction

```python
class VerificationProvider(ABC):
    name: str
    def get_services(self) -> list[ProviderServiceDTO]: ...
    def get_countries(self) -> list[ProviderCountryDTO]: ...
    def get_pricing(self, service, country) -> Decimal: ...
    def get_availability(self, service, country) -> AvailabilityDTO: ...
    def create_order(self, service, country, idem_key) -> ProviderOrderDTO: ...
    def get_order_status(self, provider_order_id) -> ProviderOrderDTO: ...
    def get_verification_code(self, provider_order_id) -> CodeDTO | None: ...
    def cancel_order(self, provider_order_id) -> bool: ...
    def refund_order(self, provider_order_id) -> bool: ...
```

* **`MockVerificationProvider`** — deterministic, scriptable, drives the whole app
  with zero credentials. Simulates assignment delay, code arrival, expiry,
  cancellation, refund and hard failure.
* **`TextVerifiedProvider`** — a real adapter whose endpoint paths, auth scheme and
  payload shapes are **left as clearly-marked `TODO(credentials)` constants**, to be
  filled in from the provider's official API documentation under an authorized
  reseller agreement. **No endpoints are invented.** See `PROVIDER_INTEGRATION.md`.

The same shape applies to `PaymentProvider` (`initiate_charge`, `verify_webhook`,
`parse_webhook`, `fetch_charge`) with `MockPaymentProvider` plus a Paystack adapter.

---

## 7. Security posture

| Threat | Control |
|---|---|
| Forged payment webhook | HMAC signature verification against the provider secret, constant-time compare, raw-body hashing |
| Replayed webhook | Unique `(provider, event_id)`; ledger `idempotency_key` unique |
| Double-spend | `SELECT FOR UPDATE` on the wallet row plus a DB `CHECK (balance >= 0)` |
| Credential leak | Secrets only in env; redaction filter in logging; no key ever reaches the frontend bundle |
| Brute force | Per-IP and per-account throttles on login/register/reset; lockout after N failures |
| Privilege escalation | Role-based permission classes on every admin route; ownership checks on every user route |
| Abuse of the service | AUP acceptance gate, purchase velocity limits, per-day spend caps, suspicious-activity scoring, admin suspension |
| Verification-code exposure | Codes are surfaced only to the ordering user, only while contractually permitted, and are excluded from logs and admin list views |

---

## 8. What must be supplied before production

These are the only blocking external dependencies. Everything else runs today on
mocks. Each is marked in code with `TODO(credentials)`.

1. **Authorized upstream verification provider** — reseller/API agreement, official
   API docs, and `PROVIDER_API_KEY`. Without this the platform runs on the mock provider.
2. **MoMo aggregator merchant account** — Paystack/Hubtel/Flutterwave keys, the
   **webhook URL** registered in their dashboard, and an IP allowlist.
3. **Exchange-rate feed** — an API key, or keep manual admin-entered rates.
4. **Transactional email provider** — SMTP/API key and a verified sending domain.
5. **Legal review** — Terms, AUP and privacy policy reviewed against Ghana's Data
   Protection Act (2012) and the aggregator's merchant terms.
