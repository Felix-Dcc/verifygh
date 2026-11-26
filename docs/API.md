# API reference

Base URL: `/api/v1/`

Versioning is in the path, so a breaking change can ship as `/api/v2/` while `/api/v1/`
keeps serving older clients.

---

## Authentication

Tokens are JWTs carried in **httpOnly cookies**, so a cross-site script cannot read them.
Because cookies are sent ambiently by the browser, unsafe methods additionally require a
double-submit CSRF token.

| Cookie | httpOnly | Purpose |
|---|---|---|
| `vgh_access` | yes | Access token (20 minutes by default) |
| `vgh_refresh` | yes | Refresh token (14 days) |
| `vgh_csrf` | **no** | Must be echoed in `X-CSRF-Token` on POST/PUT/PATCH/DELETE |

A cross-origin page cannot read `vgh_csrf`, so it cannot produce the header.

```js
fetch("/api/v1/orders/", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json", "X-CSRF-Token": readCookie("vgh_csrf") },
  body: JSON.stringify({ service: "instagram", country: "US" }),
});
```

**Bearer tokens** are also accepted (`Authorization: Bearer <token>`) for server-to-server
clients, and are exempt from the CSRF check because they are not sent ambiently.

Endpoints that authenticate from the request body — login, register, refresh, logout,
email confirm, password reset — ignore the access cookie entirely, so a signed-in browser
following an email link is never rejected by a CSRF check for a session the endpoint does
not use.

---

## Error format

Every non-2xx response has the same shape. **Switch on `code`, never on `message`.**

```json
{
  "error": {
    "code": "INSUFFICIENT_FUNDS",
    "message": "Your balance is insufficient.",
    "details": { "balance": "5.00", "required": "16.00", "shortfall": "11.00" },
    "request_id": "a1b2c3d4e5f6"
  }
}
```

Validation errors carry `details.fields`:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...",
             "details": { "fields": { "amount": ["The minimum deposit is GHS 10.00."] } } } }
```

### Codes

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 400 | Field-level problems in `details.fields` |
| `INVALID_TOKEN` | 400 | Verification or reset link invalid or expired |
| `AUTHENTICATION_REQUIRED` | 401 | No session, expired session, or CSRF check failed |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password (identical for unknown accounts) |
| `PERMISSION_DENIED` | 403 | Authenticated but not allowed |
| `ACCOUNT_SUSPENDED` | 403 | Account suspended |
| `EMAIL_NOT_VERIFIED` | 403 | Confirm your email before purchasing |
| `TERMS_NOT_ACCEPTED` | 403 | Accept the current AUP before purchasing |
| `NOT_FOUND` | 404 | Not found, or not yours |
| `CONFLICT` | 409 | Conflicts with current state |
| `INSUFFICIENT_FUNDS` | 409 | Balance too low; `details` has the shortfall |
| `INVALID_STATE_TRANSITION` | 409 | Not allowed for this status |
| `CANCEL_NOT_ALLOWED` | 409 | A code already arrived |
| `WALLET_FROZEN` | 409 | Wallet under investigation |
| `LIMIT_EXCEEDED` | 429 | A usage limit; see the specific code below |
| `RATE_LIMITED` | 429 | Throttled |
| `ACCOUNT_LOCKED` | 423 | Too many failed sign-ins |
| `PROVIDER_ERROR` | 502 | Upstream failed |
| `SERVICE_UNAVAILABLE` | 503 | Temporarily unavailable |
| `NO_EXCHANGE_RATE` / `STALE_EXCHANGE_RATE` | 503 | Cannot price right now |
| `INTERNAL_ERROR` | 500 | Unexpected |

Limit-specific codes: `TOO_MANY_ACTIVE_ORDERS`, `DAILY_ORDER_LIMIT`, `DAILY_SPEND_LIMIT`,
`TOO_MANY_PENDING_DEPOSITS`, `WALLET_CAP_EXCEEDED`, `PROVIDER_BUDGET_EXCEEDED`.

---

## Pagination

List endpoints return:

```json
{
  "results": [ ... ],
  "pagination": { "count": 137, "page": 2, "pages": 7, "page_size": 20,
                  "has_next": true, "has_previous": true }
}
```

Query with `?page=2&page_size=50` (max 100).

---

## Idempotency

Purchases accept an idempotency key, so a retry after a timeout cannot buy two numbers:

```
X-Idempotency-Key: <8-128 chars of [A-Za-z0-9._:-]>
```

or `idempotency_key` in the body. Repeating a key returns the **original order** rather
than creating a second one, enforced by `UNIQUE(user, idempotency_key)`.

Deposits are idempotent by construction: the payment reference is the ledger key, so a
replayed webhook can never credit twice.

---

## Rate limits

| Scope | Limit |
|---|---|
| Anonymous | 60/min |
| Authenticated | 240/min |
| Login | 8/min per IP **and** submitted email |
| Register | 5/hour |
| Password reset | 5/hour |
| Email verification | 10/hour |
| Deposit | 10/hour |
| Order creation | 20/hour |
| Webhooks | 600/min |

---

# Endpoints

## Auth — `/auth/`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register/` | — | Create an account. Requires `accepted_terms: true`. Signs you in. |
| POST | `/auth/login/` | — | Sign in. Sets cookies, returns `{user, csrf_token}`. |
| POST | `/auth/logout/` | — | Clears cookies. Always succeeds. |
| POST | `/auth/refresh/` | refresh cookie | New token pair. |
| GET | `/auth/me/` | yes | Current user. |
| PATCH | `/auth/me/` | yes | Update `full_name`, `phone`. |
| POST | `/auth/password/change/` | yes | `current_password`, `new_password`. Reissues tokens. |
| POST | `/auth/password/reset/` | — | Request a link. Response is identical whether or not the account exists. |
| POST | `/auth/password/reset/confirm/` | — | `token`, `new_password`. |
| POST | `/auth/email/verify/send/` | yes | Resend the confirmation link. |
| POST | `/auth/email/verify/confirm/` | — | `token`. Single use; `TOKEN_EXPIRED` and `INVALID_TOKEN` are told apart. |
| POST | `/auth/resend-verification/` | — | `email`. Answers identically whatever the address is, so it cannot be used to discover who has an account. Rate limited per (IP, address). |
| POST | `/auth/terms/accept/` | yes | `accepted: true`. Records the current version. |

`POST /auth/register/`

```json
{ "email": "kwame@example.com", "password": "at least 10 characters",
  "full_name": "Kwame Mensah", "phone": "024 123 4567", "accepted_terms": true }
```

Phone numbers are accepted in any Ghanaian format and stored as E.164.

---

## Catalog — public

| Method | Path | Description |
|---|---|---|
| GET | `/services/` | Marketplace. Filters: `category`, `country`, `search`, `available=true`. |
| GET | `/services/{slug}/` | One service with its countries and prices. |
| GET | `/services/featured/` | Up to 8 available services, for the landing page. |
| GET | `/countries/` | Enabled countries. |
| GET | `/catalog/health/` | Whether the platform can currently sell anything. |

Every price is computed server-side by the pricing engine. There is no price input
anywhere in the API.

```json
{
  "results": [{
    "slug": "instagram", "name": "Instagram", "category": "SOCIAL",
    "accent_color": "#C13584", "available": true, "from_price": "16.00", "currency": "GHS",
    "countries": [{
      "code": "US", "name": "United States", "flag_emoji": "🇺🇸",
      "dial_code": "+1", "price": "16.00", "currency": "GHS",
      "available": true, "available_count": 47,
      "supports_sms": true, "supports_voice": false, "ttl_minutes": 20
    }]
  }],
  "categories": [...], "countries": [...], "count": 16
}
```

---

## Wallet and transactions

| Method | Path | Description |
|---|---|---|
| GET | `/wallet/` | Both balances and totals. |
| GET | `/wallet/summary/` | Balances plus today's spend and order counts. |
| GET | `/transactions/` | Ledger entries. Filters: `entry_type`, `direction`, `search`. |
| GET | `/transactions/{id}/` | One entry. |

Ledger entries are immutable and carry `balance_after`, so any historical balance can be
reconstructed without replaying the table.

A wallet holds two buckets, and every entry says which one it moved (`funds`):

| Field | Meaning |
|---|---|
| `balance` | Cash the user paid in. Withdrawable, refunded as cash. |
| `promo_balance` | Promotional credit (referral bonuses). Spendable on verifications, **never** withdrawable, transferable or convertible. |
| `spendable` | `promo_balance + balance` — what a purchase can draw on. |

A purchase spends promotional credit first and writes one entry per bucket. A refund
returns each bucket to itself. See [REFERRALS.md](REFERRALS.md).

---

## Referrals

| Method | Path | Description |
|---|---|---|
| GET | `/referrals/me/` | Your code, link, the current bonus and your stats. |
| GET | `/referrals/stats/` | Successful, pending, rejected, credit issued. |
| GET | `/referrals/history/` | Your invitations. Emails are masked (`k***@example.com`). |
| POST | `/referrals/validate/` | `{"code": "VGH8K4P2"}` → `{"valid": true, "bonus_amount": "5.00"}`. Anonymous, throttled, and says nothing about the code's owner. |

Registration accepts an optional `referral_code`. The backend resolves it and records the
attribution itself; an unknown code is ignored and registration continues. An account has
exactly one referrer, for ever.

**There is no claim endpoint.** Eligibility is decided by the backend — after email
verification, an admin review, or the periodic sweep — and the reward is issued through the
ledger. Nothing the browser sends can award credit.

---

## Payments

| Method | Path | Description |
|---|---|---|
| GET | `/payments/options/` | Supported networks, limits, quick amounts. Served dynamically. |
| POST | `/payments/deposit/` | Start a MoMo collection. |
| GET | `/payments/` | Your payments. |
| GET | `/payments/{reference}/` | One payment. |
| POST | `/payments/{reference}/refresh/` | Ask the provider directly and apply their answer. The waiting screen polls this; the provider is asked at most once every 4 seconds per payment, otherwise it answers from our record. |
| POST | `/payments/webhooks/{provider}/` | Provider callback. Unauthenticated, signature-verified. |

`POST /payments/deposit/`

```json
{ "amount": "50.00", "phone": "024 123 4567" }
```

`network` is optional — we infer it from the prefix and prefer the prefix over a supplied
value, because sending a charge to the wrong network simply fails at the aggregator.

**The response never means the money arrived.** The payment starts `PENDING`/`PROCESSING`
and only a verified webhook (or `refresh`) can make it `SUCCESS`.

### Webhooks

```
POST /api/v1/payments/webhooks/paystack/
x-paystack-signature: <HMAC-SHA512 of the raw body>
```

* Signature is verified against the **raw bytes**, in constant time.
* Invalid signature → `401`, nothing else happens, the attempt is recorded.
* Verified events are stored raw before being acted on, with `UNIQUE(provider, event_id)`.
* Duplicates return `200 {"status": "duplicate"}` — telling a provider to retry an event we
  have already handled helps nobody.
* An amount mismatch credits **what actually arrived** and raises a high-severity flag.

---

## Orders

| Method | Path | Description |
|---|---|---|
| GET | `/orders/quote/?service=&country=` | Server-side price plus your balance. |
| GET | `/orders/eligibility/` | What would block a purchase, if anything. |
| POST | `/orders/` | Buy a number. |
| GET | `/orders/` | Your orders. Filters: `filter=active\|completed\|failed\|refunded`, `status`, `search`. |
| GET | `/orders/active/` | Up to 10 in-flight orders. |
| GET | `/orders/{reference}/` | Full order with its timeline. |
| GET | `/orders/{reference}/status/` | Lightweight polling. |
| POST | `/orders/{reference}/complete/` | Mark complete (only after a code arrives). |
| POST | `/orders/{reference}/cancel/` | Cancel and refund (only before a code arrives). |

`POST /orders/`

```json
{ "service": "instagram", "country": "US", "idempotency_key": "optional" }
```

**Note what is absent: price.** The client says what it wants, never what it costs. Any
price-like field in the body is ignored, and the server prices the order from the catalogue
on every request.

`GET /orders/{reference}/status/` is what the live order screen polls. It reads our own
database, and additionally asks the provider only when the order is genuinely waiting and
we have not asked within `poll_interval_seconds` — so a user holding the screen open cannot
turn into a stream of upstream calls.

```json
{ "reference": "VGH-8X2CRJ", "status": "CODE_RECEIVED",
  "phone_number": "+13278273360", "verification_code": "457770",
  "code_display_allowed": true, "seconds_remaining": 742,
  "refund_status": "NONE", "failure_reason": "", "poll_interval_seconds": 5 }
```

`verification_code` is returned **only** to the ordering user and **only** when the provider
agreement permits relaying it. Otherwise it is an empty string and
`code_display_allowed` is `false`.

### Order statuses

```
CREATED → PAYMENT_PENDING → PROCESSING → NUMBER_ASSIGNED → WAITING_FOR_CODE
                                │                                │
                                │                                ├─ CODE_RECEIVED → COMPLETED
                                │                                └─ EXPIRED ──┐
                                ├─ FAILED ─────────────────────────────────────┤
                                └─ CANCELLED ──────────────────────────────────┤
                                                                               ▼
                                                                           REFUNDED
```

Illegal transitions raise rather than silently writing.

---

## Notifications

| Method | Path | Description |
|---|---|---|
| GET | `/notifications/` | In-app notifications. |
| GET | `/notifications/unread/` | `{ "count": 3 }`. |
| POST | `/notifications/{id}/read/` | Mark one read. |
| POST | `/notifications/read-all/` | Mark all read. |

Verification codes are never placed in a notification body.

---

## Admin — `/admin/`

Every endpoint requires a staff role **and** the specific permission from the matrix in
`apps/accounts/constants.py`. Suspensions, wallet adjustments and refunds require a written
reason and write an immutable `AdminAction` **before** the effect is applied.

| Method | Path | Permission |
|---|---|---|
| GET | `/admin/overview/` | `METRICS_VIEW` |
| GET | `/admin/charts/?days=14` | `METRICS_VIEW` |
| GET | `/admin/health/` | `METRICS_VIEW` |
| GET | `/admin/users/` | `USER_VIEW` |
| POST | `/admin/users/{id}/suspend/` | `USER_SUSPEND` |
| GET | `/admin/referrals/` | `REFERRAL_VIEW` |
| POST | `/admin/referrals/{id}/approve\|reject\|flag/` | `REFERRAL_MANAGE` |
| POST | `/admin/referrals/{id}/reverse-reward/` | `WALLET_ADJUST` |
| GET | `/admin/referrals-analytics/` | `REFERRAL_VIEW` |
| GET\|PATCH | `/admin/referral-program/` | `REFERRAL_VIEW` / `PRICING_MANAGE` |
| POST | `/admin/users/{id}/unsuspend/` | `USER_SUSPEND` |
| POST | `/admin/users/{id}/wallet-adjustment/` | `WALLET_ADJUST` |
| GET | `/admin/users/{id}/orders/` | `USER_VIEW` |
| GET | `/admin/users/{id}/transactions/` | `WALLET_VIEW` |
| GET | `/admin/users/{id}/activity/` | `USER_VIEW` |
| GET | `/admin/orders/` | `ORDER_VIEW` |
| GET | `/admin/orders/{ref}/timeline/` | `ORDER_VIEW` |
| POST | `/admin/orders/{ref}/cancel/` | `ORDER_CANCEL` |
| POST | `/admin/orders/{ref}/refund/` | `ORDER_REFUND` |
| GET | `/admin/refunds/` | `ORDER_VIEW` |
| GET | `/admin/payments/` | `PAYMENT_VIEW` |
| GET/PATCH | `/admin/services/{slug}/` | `CATALOG_MANAGE` |
| GET/PATCH | `/admin/countries/{code}/` | `CATALOG_MANAGE` |
| GET/PATCH | `/admin/offerings/` | `CATALOG_MANAGE` |
| POST | `/admin/offerings/sync/` | `PROVIDER_MANAGE` |
| CRUD | `/admin/pricing-rules/` | `PRICING_MANAGE` |
| POST | `/admin/pricing-rules/preview/` | `PRICING_MANAGE` |
| GET/POST | `/admin/exchange-rates/` | `PRICING_MANAGE` |
| GET | `/admin/audit/` | `AUDIT_VIEW` |
| GET | `/admin/admin-actions/` | `AUDIT_VIEW` |
| GET | `/admin/flags/` | `USER_VIEW` |
| POST | `/admin/flags/{id}/resolve/` | `USER_SUSPEND` |
| GET\|POST | `/admin/api-keys/` | any staff, own keys only; POST needs a two-factor `code` |
| POST | `/admin/api-keys/{id}/revoke/` | any staff, own keys only |

### Admin API keys

For a program or an assistant that has no browser session. Create one under
**Admin → API keys** (two-factor code required; shown once), then send it as a Bearer token:

```bash
curl -H "Authorization: Bearer vgh_ak_<prefix>_<secret>" \
  https://api.getverifygh.com/api/v1/admin/flags/
```

A key acts as its owner with the owner's **current** role, on `/admin/` endpoints only. It
never reaches customer endpoints or `/admin/api-keys/`. `READ` keys may only `GET`. Keys
expire after 1, 7, 30 or 90 days (at most five live at once), and stop working at once when
revoked, when the owner signs out everywhere or changes password, or when the owner is
suspended or removed from staff. A refused key returns `401`; a key used outside its scope
returns `403`. Actions taken with a key carry `via_admin_key` in the audit log.

### Roles

| | SUPPORT | ADMIN | SUPER_ADMIN |
|---|:-:|:-:|:-:|
| View users, orders, payments, wallets, metrics, referrals | ✓ | ✓ | ✓ |
| Suspend users, cancel orders, refund, manage catalog, view audit, decide referrals | | ✓ | ✓ |
| Change roles, adjust wallets, reverse referral credit, manage pricing and providers | | | ✓ |

The admin order list exposes `has_code` (whether a message arrived) but **never the code
itself** — support can confirm delivery without reading a customer's one-time code.

---

## Health

| Method | Path | Description |
|---|---|---|
| GET | `/health/` | Liveness and readiness. Checks the database. Returns 503 if it is unreachable. |
