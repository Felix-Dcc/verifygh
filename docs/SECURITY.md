# Security

VerifyGH holds customer money. This document states what it protects against, how, and
where the limits are.

---

## 1. Financial integrity

This is the part that matters most. Everything else is recoverable; a wrong balance is not.

### One writer

`apps/wallet/services.py` is the **only** code in the project that writes `Wallet.balance`.
Not a view, not a task, not the Django admin. Any future code that needs to move money must
go through `post_entry`.

### The balance is a cache; the ledger is the truth

`WalletLedgerEntry` is append-only. Each row records `balance_before`, `balance_after` and a
per-wallet `sequence` assigned under the wallet lock. `Wallet.balance` is a projection of
that table, re-derived nightly by `reconcile_wallets`, which **reports drift rather than
silently correcting it** — quietly fixing the number would destroy the evidence.

The integrity check also walks the sequence: a gap means a row was deleted, and a mismatch
between one row's `balance_after` and the next row's `balance_before` means a row was
written outside the service.

Timestamps are deliberately not the ordering key. On a coarse system clock several entries
share a millisecond, and a ledger with no defined order is not a ledger.

### Idempotency is a database constraint, not a check

```sql
UNIQUE (wallet_id, idempotency_key)     -- wallet_ledger_entry
UNIQUE (provider, event_id)             -- payments_webhook_event
UNIQUE (user_id, idempotency_key)       -- orders_order
UNIQUE (order_id)                       -- orders_refund (one refund per order)
```

"Check then act" in Python loses races. A unique index does not. A replayed webhook loses
to the index and returns the original entry.

### Double-spend

Concurrent debits are serialised three ways:

1. `SELECT ... FOR UPDATE` on the wallet row, where the backend supports it.
2. A **compare-and-set** balance update (`WHERE balance = <value read>`) with a rowcount
   assertion and bounded retry — correct even without row locks.
3. `CHECK (balance >= 0)` as the last line of defence.

`tests/test_concurrency.py` runs real threads against real connections:

* ₵20 balance, two simultaneous ₵15 purchases → exactly one succeeds, balance ₵5.
* ₵50 balance, ten simultaneous ₵10 purchases → exactly five succeed, balance ₵0.
* Five simultaneous identical webhooks → one credit.

### Atomicity boundaries

Money moves inside one transaction. The **provider is called outside it** — holding a
database transaction open across a third-party network call is how you get lock pile-ups
and cascading timeouts under load. If the provider then fails, the order is refunded, which
is a new transaction of its own.

---

### Promotional credit is not money

Referral bonuses live in a second bucket of the same wallet (`promo_balance`) and move
through the same ledger service, with the same lock, the same compare-and-set and the same
idempotency key. The separation is enforced by the database rather than by convention:

* `ledger_funds_allow_entry_type` - a `WITHDRAWAL` may only move `CASH` and a
  `REFERRAL_BONUS` only `PROMO`, so promotional credit has **no exit path**;
* refunds return each bucket to itself, and partial-refund rounding favours the
  promotional side, so nothing converts credit into withdrawable cash;
* one signup bonus per account, checked against the ledger itself;
* the reward is idempotent three times over - a row lock, a `OneToOne` on the reward, and a
  ledger key derived from the referral id. Ten concurrent calls credit GH₵5 once.

Abuse signals (shared device, referral velocity, duplicate accounts) **hold** a referral for
human review rather than rejecting it, and are never shown to customers. A shared IP address
is recorded but never blocking: in Ghana, homes, offices, schools, hostels and mobile
networks all put many legitimate people behind one address. See
[REFERRALS.md](REFERRALS.md).

---

## 2. Payments

**The client never confirms a payment.** A deposit becomes money through exactly one of two
paths: a signature-verified provider webhook, or our own outbound `fetch_charge` during
reconciliation.

| Control | Implementation |
|---|---|
| Signature verification | HMAC over the **raw request bytes**, constant-time compare. Re-serialising parsed JSON changes whitespace and key order and would verify a forged body. |
| Replay | `UNIQUE(provider, event_id)` plus the ledger key. Duplicates answer `200`, not an error — a provider retrying an event we handled helps nobody. |
| Unsigned / bad signature | `401`, nothing is read out of the body, the attempt is recorded with a hash of it. |
| Amount mismatch | Under-payment credits **what actually arrived**. An over-payment beyond 5% is **held for review**, not credited — it is far likelier a provider bug than a gift. Both raise a high-severity flag. |
| Provider binding | A callback only settles a payment made **with that provider**, and only the active provider's webhook endpoint is reachable (`WEBHOOK_PROVIDERS` for a switchover). Production refuses to boot with the mock endpoint live. |
| Failed processing | A verified event that fails to apply is re-applied on the provider's retry, and a sweep every 5 minutes finishes any the provider gave up on. Re-application is safe because of the ledger key. |
| Unparseable event | A verified callback we cannot parse is stored and counted as unprocessed on `/admin/health`, never silently acknowledged and lost. |
| Late reversal | A settled payment never walks backwards on a late callback. |
| Lost webhook | `reconcile_recent_payments` asks the provider directly, every 15 minutes. A user who paid and got nothing is the worst possible failure. |
| Premature expiry | `expire_stale_payments` asks the provider **before** writing a payment off. |
| Raw retention | Every verified event is stored raw (redacted of credential-shaped values) so a dispute can be reconstructed months later. |

Before go-live, also restrict the webhook path to your provider's published IP range at the
edge. Signature verification is the real control; the IP allowlist is defence in depth.

---

## 3. Authentication and sessions

| Control | Implementation |
|---|---|
| Password storage | Argon2 (`argon2-cffi`), with PBKDF2 and bcrypt accepted for legacy rehash |
| Password policy | Minimum 10 characters plus Django's similarity, common-password and numeric validators |
| Token transport | httpOnly, `Secure` in production, `SameSite` configurable; JavaScript cannot read them |
| CSRF | Double-submit — a readable `vgh_csrf` cookie must be echoed in `X-CSRF-Token` on every unsafe method. A cross-origin page cannot read our cookie. |
| Bearer tokens | Accepted for API clients and exempt from CSRF, because they are not sent ambiently |
| Brute force | 8/min per (IP, email) against guessing one password; 30/min per IP against credential stuffing; database-backed account lockout that works even if the cache is down |
| Client IP | Read `TRUSTED_PROXY_COUNT` hops from the **right** of `X-Forwarded-For` — never the client-writable leftmost entry. Governs rate limits, audit logs and device signals. |
| Enumeration | Wrong password and unknown email return byte-identical responses. Password reset always answers the same. |
| Reset tokens | Only a SHA-256 hash is stored, single-use, 2-hour expiry, and issuing a new one invalidates the old |
| Password change / reset | Revokes every session (see below); the tab that changed it gets a fresh pair |
| Sign-out | Never requires a valid session — requiring one to end one is how users get stuck |
| Human check | Cloudflare Turnstile on sign-in and sign-up once `TURNSTILE_SECRET_KEY` is set. The token is checked with Cloudflare before any password is tried or account created. It is single use, must match the form's action and, optionally, our hostnames. The check fails closed, and a refusal never counts towards the lockout. |
| Sign in with Google | OpenID Connect authorisation-code flow run by the API, with PKCE, `state` and `nonce` in a signed, HttpOnly, callback-scoped cookie. The ID token comes straight from Google's token endpoint over TLS (OIDC Core 3.1.3.7). Issuer, audience, expiry, nonce and `email_verified` are all checked. Accounts are matched by Google's `sub`, then by verified email. Linking to an account whose email was never verified retires its password and ends its sessions, against account pre-hijacking. No Google script runs on our pages. See [GOOGLE_SIGN_IN.md](GOOGLE_SIGN_IN.md). |

### Session revocation

JWTs are self-contained, so signing out has to be made true rather than assumed. Two
mechanisms cover two different windows:

| Mechanism | Revokes | Used on |
|---|---|---|
| Refresh-token **blacklist** (`token_blacklist`, `BLACKLIST_AFTER_ROTATION=True`) | One refresh token | Sign-out; every refresh (so a replayed old refresh token fails) |
| **`token_version`** claim on every token, checked on every request | *Everything* a user holds, including access tokens already issued | Password change, password reset, suspension, **refresh-token reuse** |

**Reuse detection.** If a refresh token that was already rotated comes back more than 30
seconds later, two parties hold the same credential. We cannot tell the user from the thief,
so every session ends and a HIGH abuse flag is raised (RFC 9700 §4.14.2). Inside the 30
seconds, a replay is treated as two tabs refreshing at once: it is refused, and nothing else
happens. Rotation claims a unique blacklist row, so two concurrent refreshes of one token
cannot both mint a new pair.

Blacklisting alone would leave a stolen access token working for its full 20-minute
lifetime after a password reset. The version check closes that: the next request fails.

There is exactly one authentication class. A second, plain `JWTAuthentication` fallback
would have let bearer tokens skip both checks. A suspended user's token is rejected
immediately with `403 ACCOUNT_SUSPENDED`. Expired blacklist rows are flushed nightly.

**Two-factor sign-in** (`apps/accounts/two_factor.py`). Authenticator-app codes (RFC 6238
TOTP, 6 digits, 30 s, one step of drift), each accepted once, plus ten single-use recovery
codes stored as keyed hashes. With it on, the password step returns a signed five-minute
challenge (httpOnly cookie) tied to the session epoch, and `/auth/2fa/verify/` exchanges it
and a code for a session, once; wrong codes count towards the password lockout. Google
sign-in takes the same step. Staff must have it to use any admin endpoint while
`STAFF_TWO_FACTOR_REQUIRED` is on (the default; off in dev and tests). A super admin can reset
another staff member's two-factor with a reason, which ends their sessions. The TOTP secret is
stored unencrypted in the user row, like most implementations; encrypting it at rest would
need a key outside the database.

---

## 4. Authorization

* Every user-facing queryset is **filtered by owner**, so an object-level check is never the
  only thing between two customers' data. A wrong reference returns `404`, not `403` — it
  does not confirm that an order exists.
* The wallet endpoint takes no id at all: a user can only ever address their own.
* Admin endpoints check a staff role **and** a specific permission from the matrix in
  `apps/accounts/constants.py`. SUPPORT can read a wallet and not adjust one; only
  SUPER_ADMIN can change pricing or roles.
* An admin cannot suspend themselves, and only a SUPER_ADMIN can suspend another admin.
* **Admin API keys** (`apps/accounts/api_keys.py`) let a staff member hand a program access
  without a browser session. They are narrower than a session on purpose: admin endpoints
  only, never key management, the owner's live role (not a snapshot), a hard expiry of at most
  90 days, optional read-only, and they die with "sign out everywhere", a password change,
  suspension or removal from staff. Creating one needs a fresh two-factor code. Only a SHA-256
  hash is stored (the secret is 256 random bits, so a slow hash buys nothing), keys are
  redacted from logs, and every action taken with one is tagged in the audit log.

---

## 5. Abuse prevention

The product's position is that it is for legitimate verification. That is enforced, not
merely stated.

| Control | Default |
|---|---|
| AUP acceptance before purchase | required, version recorded |
| Email confirmation before purchase | required (`REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE`) |
| Concurrent active orders | 5 |
| Orders per 24h | 25 |
| Spend per 24h | GHS 1,500 |
| Single deposit | GHS 5 – 2,000 |
| Wallet balance cap | GHS 10,000 |
| Unapproved pending deposits | 3 |
| Upstream call budget | 120/min, enforced in front of every provider adapter |

Abuse signals (`SuspiciousActivity`) are recorded for shared devices, order velocity,
deposit anomalies and repeated failed sign-ins. **They never auto-suspend an account** — a
shared device is an internet cafe as often as it is abuse. A human decides, with a written
reason, and that decision is itself recorded.

Device fingerprints are stored as a salted hash of user agent plus IP, never raw, and are
used only to flag one device driving many accounts.

---

## 6. Provider terms

There is no scraping, no browser automation, no CAPTCHA handling and no rate-limit evasion
anywhere in this codebase. The adapter makes authenticated HTTPS calls to documented
endpoints and nothing else.

A `429` from a provider is surfaced as a retryable error and backed off, never retried
through. `RateLimitedProvider` wraps every adapter so no caller can reach past the budget.

`TextVerifiedProvider` deliberately ships with **empty endpoint constants**. Inventing an
endpoint produces code that looks finished and fails in production; a blank constant raises
a clear "not configured" error instead.

---

## 7. Data protection

| | |
|---|---|
| Never collected | MoMo PIN, card details, location, contacts, advertising identifiers |
| Never logged | Verification codes, message bodies, credentials, tokens, signatures |
| Masked in logs | Phone numbers (`024***4567`) |
| Redaction | A logging filter strips anything credential-shaped from messages, structured fields and stored webhook payloads |
| Code exposure | Codes go only to the ordering user, only while the provider agreement permits, and never appear in admin list views or notification bodies |
| Cookies | Session and CSRF only. No analytics, advertising or tracking cookies. |

---

## 8. Transport and headers

Production (`config/settings/prod.py`) enforces HTTPS redirect, HSTS with preload,
`Secure` cookies, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: same-origin`. The frontend sets the same headers plus a restrictive
`Permissions-Policy`.

CORS is an explicit allowlist with credentials enabled. `*` is never valid here.

### Behind Cloudflare

See [CLOUDFLARE.md](CLOUDFLARE.md). The client IP comes from `CF-Connecting-IP`
only on requests carrying the origin secret that Cloudflare's Transform Rule sets
(`X-VerifyGH-Origin`); everything else falls back to `X-Forwarded-For` with
`TRUSTED_PROXY_COUNT`. With `CLOUDFLARE_MODE=enforce`, both the API and the
website refuse requests without that secret, so the Railway addresses cannot be
used to go around Cloudflare. Rate limits key on the same resolved IP.

### Content-Security-Policy

**Frontend** (`frontend/src/proxy.ts`) — a fresh nonce per request:

```
script-src 'self' 'nonce-<per request>' 'strict-dynamic'
style-src 'self' 'unsafe-inline'
connect-src 'self' <API origin only>
frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'
upgrade-insecure-requests
```

No `'unsafe-inline'` or `'unsafe-eval'` for scripts in production. Inline *styles* are
allowed because Next injects them and a nonce cannot reach all of them; style cannot
execute. Development additionally allows `'unsafe-eval'` and `ws:` for hot reload.

Every page renders per request (`dynamic = "force-dynamic"` in the root layout). This is
required, not a preference: a page prerendered at build time has no request, so no nonce,
and the policy blocks all of its scripts. Verified against a production build — zero
violations across client-side navigation, including lazily loaded chunks.

**API** (`apps/common/security.py`) — `default-src 'none'; frame-ancestors 'none'`. It
serves JSON, so nothing legitimate breaks. Django admin gets a narrower policy that still
permits the inline code its templates ship. API responses are also `Cache-Control:
no-store` — they carry balances and must never sit in a shared cache.

---

## 9. Configuration safety

`config/settings/prod.py` refuses to boot when:

* any of `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`
  or `FRONTEND_URL` is missing,
* `SECRET_KEY` still holds a development value,
* `PAYMENT_PROVIDER=mock` — you cannot accidentally run production on a fake payment
  provider,
* `PAYMENT_PROVIDER=paystack` without `PAYSTACK_SECRET_KEY` — a live provider without a
  webhook secret would accept forged callbacks.

Failing at boot is much cheaper than discovering this at 2am.

---

## 10. Audit

`AuditLog` records every state change; `AdminAction` records every privileged one with its
mandatory reason, before/after values, actor, IP and request id. Both use `ImmutableModel`,
which raises on update. `record_audit` never fails a user's action; `record_admin_action`
raises, because an unexplained balance change is exactly what an audit exists to catch.

Every request carries a request id through every log line and into the error envelope, so a
customer's screenshot maps to a specific trace.

---

## 11. Before you take real money

- [ ] Rotate `SECRET_KEY` and `JWT_SIGNING_KEY`; never reuse development values
- [ ] `DEBUG=false`, real `ALLOWED_HOSTS`, `AUTH_COOKIE_SECURE=true`
- [x] ~~Enable the JWT blacklist app and `BLACKLIST_AFTER_ROTATION`~~ — done, plus `token_version`
- [x] ~~Add a Content-Security-Policy~~ — done, nonce-based, verified on a production build
- [ ] Set `TRUSTED_PROXY_COUNT` to your real proxy depth (Render: 1) — see `docs/AUDIT.md` F-04
- [ ] Run CI once against PostgreSQL and confirm the concurrency tests pass there
- [ ] Restrict the webhook path to the provider's published IPs at the edge
- [ ] Turn on database backups with point-in-time recovery and **test a restore**
- [ ] Wire `reconcile_wallets` failure to a pager, not an inbox
- [ ] Alert on unprocessed webhooks (`/admin/health/` exposes the count)
- [ ] Error monitoring (Sentry or equivalent) with the redaction filter verified
- [ ] Legal review of the Terms, AUP and Privacy Policy against Act 843
- [ ] An independent penetration test of the payment and authentication paths

---

## Reporting a vulnerability

Email **support@getverifygh.com** with "Security" in the subject. Please include reproduction steps and do not test
against production balances. We aim to acknowledge within two business days.
