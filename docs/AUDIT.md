# Pre-production audit

**Date:** 18–19 September 2026 · **Scope:** the whole repository, before production
credentials are connected · **Result:** two passes, 33 findings, all fixed and covered by
tests. The items that remain need an external party or infrastructure. The most important is
**O-1: the suite has not yet run on PostgreSQL.** Until it has, VerifyGH is **not** production-ready.

Every finding below was **reproduced before it was fixed** — either by an exploit test that
succeeded against the old code, or by reading the exact failing path. Each fix has a
regression test named in the table, so none of these can quietly come back.

| | Before | After |
|---|---|---|
| Backend tests | 153 | **317 passed, 5 PostgreSQL-only skipped locally** |
| Critical findings open | 2 | **0** |
| High findings open | 9 | **0** |
| Medium findings open | 11 | **0** |

---

## Findings

Severity is rated against this system: it holds customer money, so anything that can
create, lose or misdirect a cedi is Critical.

### Critical

**F-01 · A forged webhook could credit any wallet** — *Payment webhooks* · Fixed

`_apply_event` looked a payment up by reference alone and never checked which provider it
belonged to. The mock adapter stayed registered in production, signing with a secret that is
published in `.env.example`. Start a real Paystack deposit, take its reference, post a
mock-signed "success" to `/payments/webhooks/mock/` — **reproduced: ₵500 credited, nothing paid.**

Fixed in three independent layers: only the active provider's webhook endpoint is reachable
(others return 404); a callback can only settle a payment made with its own provider
(mismatches raise a HIGH flag); production refuses to boot with the mock endpoint enabled.
*Tests:* `test_a_mock_signed_webhook_cannot_settle_a_live_provider_payment`,
`test_an_enabled_provider_still_cannot_settle_another_providers_payment`.

**F-02 · A webhook that failed once was never applied** — *Payment webhooks* · Fixed

The event row was written, then applying it raised (a DB blip, a lock timeout). The endpoint
returned 5xx and the provider retried — but the retry hit the unique index and was answered
`duplicate`. **The customer paid and was permanently uncredited**, with no automatic path to
recovery.

The retry now re-applies any verified-but-unprocessed event; a sweep every 5 minutes finishes
events the provider stopped retrying. Re-application is safe because the ledger's unique
idempotency key turns a second credit into a no-op.
*Tests:* `test_a_failed_webhook_is_reapplied_when_the_provider_retries`,
`test_the_sweep_recovers_a_webhook_the_provider_gave_up_on`,
`test_replaying_an_already_applied_webhook_does_not_double_credit`.

### High

**F-03 · Sessions could not be revoked** — *Authentication* · Fixed

Refresh tokens rotated but were never blacklisted, so a stolen one stayed usable for 14 days.
Worse, **access tokens survived a password reset or a suspension** for their full lifetime —
blacklisting refresh tokens alone would not have fixed that. And the settings listed plain
`JWTAuthentication` as a fallback, so any fix applied to the cookie path would have been
skipped by bearer tokens.

Fixed with two mechanisms: the `token_blacklist` app with `BLACKLIST_AFTER_ROTATION`, and a
`token_version` claim on every token, checked on every request. Password change, password
reset and suspension bump the version, killing every token at once. One authentication
class, no fallback. Expired blacklist rows are flushed nightly.
*Tests:* all 14 in `test_token_revocation.py`, including
`test_bumping_the_epoch_kills_an_issued_access_token` and
`test_bearer_tokens_cannot_skip_the_revocation_check`.

**F-04 · Every rate limit could be bypassed with a fake header** — *Rate limiting* · Fixed

DRF's `NUM_PROXIES` was unset, which makes it use the *entire client-supplied*
`X-Forwarded-For` as the throttle key; our own `get_client_ip` trusted the leftmost entry,
which the client writes. **Reproduced: 20 sign-in attempts with rotating fake headers, 0
throttled.** The same forgeable IP fed audit logs, login telemetry and device-sharing signals.

A single `TRUSTED_PROXY_COUNT` setting now drives both, reading from the *right* of the
header. **Set it to 1 on Render** — it defaults to 0 (ignore the header).
*Tests:* `test_a_spoofed_forwarded_header_does_not_reset_the_login_limit`,
`test_client_ip_ignores_the_forged_leftmost_hop`.

**F-05 · Credential stuffing was never throttled** — *Rate limiting* · Fixed

The login bucket was keyed on IP *and* email, so one address trying a leaked list against
thousands of accounts got a fresh bucket per account. **Reproduced: 20 different emails from
one IP, 0 throttled.** Added a per-IP bucket (30/min) alongside the per-account one.
*Test:* `test_credential_stuffing_from_one_address_is_throttled`.

**F-06 · No Content-Security-Policy — and the obvious one breaks production** —
*Error handling / frontend* · Fixed

Implemented a per-request nonce policy with `'strict-dynamic'` and no inline or eval script.
Testing the **production build** (not dev) showed it blocked every script and the app never
hydrated: prerendered pages have no request, so no nonce. Fixed by rendering per request.
Verified on a production build: every script carries the request's nonce, and **zero
violations** across client-side navigation including lazily loaded chunks. Full policy in
`SECURITY.md`. The API gets `default-src 'none'` plus `Cache-Control: no-store`.

**F-07 · A signed but unparseable callback vanished** — *Payment webhooks* · Fixed

If a verified callback could not be parsed (a new event type, an API change), it was answered
200 and never stored — the provider stopped retrying and the payment was lost silently. Also,
the "could not record" branch answered 200. Unparseable events are now stored and counted as
unprocessed on `/admin/health`; the unrecorded branch answers 503 so the provider retries.
*Test:* `test_a_verified_but_unparseable_webhook_is_kept_for_a_human`.

### Medium

| ID | Area | Finding | Fix | Test |
|---|---|---|---|---|
| F-08 | Wallet accounting | Any over-payment was credited, so a provider bug reporting 100× the amount would hand out money never received | Over-payments beyond 5% are held for review, not credited; under-payments still credit what arrived | `test_a_large_overpayment_is_held_not_credited` |
| F-09 | Provider abstraction | Production would boot with `VERIFICATION_PROVIDER=mock` and sell simulated numbers for real cedis | Production refuses; run `textverified` (inert until configured) instead | `test_production_refuses_to_sell_mock_numbers` |
| F-10 | Error handling | DRF's browsable API was served in production, mapping every endpoint for anyone sending `Accept: text/html`. Its on/off switch read `DEBUG` from the environment, not from the settings module | JSON-only, pinned in `prod.py` independent of the environment | `test_the_browsable_api_is_not_served_outside_debug` |
| F-11 | Refunds / orders | Orders with a delivered code were never closed. They count toward the 5-active-order limit, so a customer who never tapped "complete" was eventually **locked out of buying** | Auto-completed (never refunded) once the number's window passes. Automatic refunds now also check for a delivered code directly, not only the status | `test_delivered_orders_are_auto_completed_...`, `test_an_automatic_refund_never_follows_a_delivered_code` |
| F-12 | Rate limiting | A Redis outage made every throttled request raise — rate limiting became the outage | Throttles fail open and log at ERROR. Safe because the login lockout is in the database | `test_throttling_fails_open_when_the_cache_is_down`, `test_account_lockout_still_protects_login_without_the_cache` |
| F-13 | Payment webhooks | `reconcile_recent_payments` — the rescue for lost webhooks — existed but was never scheduled | Every 15 minutes | Beat schedule |

### Low

| ID | Area | Finding | Fix |
|---|---|---|---|
| F-14 | Logging | Redaction matched sensitive words as substrings, scrubbing `error_code`, `status_code`, `country_code`, `token_version` — the fields you search during an incident | Anchored to whole keys; codes, tokens and keys still redacted (`test_logging.py`, 8 tests) |
| F-15 | Logging / privacy | Blacklist rows and login telemetry grew forever; the Privacy Policy promises ~12 months | Nightly token flush; weekly pruning of login attempts past 365 days |
| F-16 | Authorization | SUPPORT could dismiss abuse signals, hiding them from everyone | Dismissal now needs `USER_SUSPEND` (ADMIN) |
| F-17 | Secrets | `JWT_SIGNING_KEY` silently fell back to `SECRET_KEY` | Required and separate in production |
| F-18 | Authentication | The stored outstanding-token record was a string never actually issued | Synced to the issued token |
| F-19 | Authentication | After F-03, a suspended user got `401` and was bounced to sign-in | `403 ACCOUNT_SUSPENDED`, token still dead |

### Second pass (19 September): Paystack, sessions, admin, deployment

The first pass tested the Paystack adapter only through the mock, so these tests now send
real HMAC-signed Paystack payloads through the HTTP endpoint (`test_paystack_webhooks.py`,
22 tests).

| # | Sev. | Area | Problem | Fix | Test |
|---|---|---|---|---|---|
| F-20 | High | Payment webhooks | **Every genuine Paystack webhook was rejected.** Django passes header names in Title-Case (`X-Paystack-Signature`), but the adapter looked them up in lowercase, so no signature was ever found. Deposits would only have been credited by the 15-minute reconciliation sweep. | The view lowercases header names once; every adapter reads lowercase | `test_a_correctly_signed_charge_success_credits_the_wallet` |
| F-21 | High | Payment webhooks | The Paystack event id was the *transaction* id, which every event about a transaction shares. The first event for a payment swallowed every later one as a "duplicate", including the success. Non-final events also stamped `completed_at`. | Event id is `event:transaction_id`; non-final events are recorded and change nothing | `test_later_events_for_the_same_transaction_are_not_swallowed` |
| F-22 | High | Payment webhooks | Any event with `data.status == "success"` confirmed a deposit, including `transfer.success` and `refund.processed` | Only `charge.success` can credit; disputes raise a HIGH flag for a human and never reverse anything automatically | `test_non_charge_events_never_confirm_a_deposit` (4 events), `test_a_dispute_is_flagged_...` |
| F-23 | High | Authentication | A replayed (already rotated) refresh token was refused, but that was all: the thief's other copy kept working. Two simultaneous refreshes could also both mint a new pair from one token. | Replay outside a 30-second two-tab grace window **ends every session** the user has and raises a HIGH flag (RFC 9700 §4.14.2). Rotation takes a unique blacklist row, so exactly one request wins. | `test_replaying_a_rotated_token_ends_every_session`, `test_only_one_rotation_of_a_token_can_succeed` +3 |
| F-24 | High | Secrets | With no `.dockerignore`, `COPY backend/ /app/` baked the local `.env` (a SECRET_KEY and the mock webhook secret), `.venv` and the SQLite databases into every image. Production settings also read `.env`, so a stray file could fill in any variable the operator forgot, with development values. | Root `.dockerignore`; `.env` is never loaded when the settings module is `config.settings.prod` | `test_a_dotenv_file_is_ignored_in_production` |
| F-25 | Medium | Payment webhooks | Currency was never checked: a USD 50 charge credited GHS 50 | Mismatched currency is held for review, not credited | `test_a_charge_in_another_currency_is_held_not_credited` |
| F-26 | Medium | Secrets / startup | Production booted with a Paystack **test** key (every "payment" free, wallets credited for real), a public `pk_` key, short secrets, the JWT key equal to `SECRET_KEY`, an unset proxy count, an unencrypted database link, or `http://` origins | Each one refuses to boot. Test keys need an explicit `ALLOW_PAYSTACK_TEST_KEYS=true` for staging. The mock-verification guard is unchanged. | `test_startup_safety.py`: safe baseline boots; 17 single-change cases refuse |
| F-27 | Medium | Admin | The admin record was written **before** the effect and outside its transaction. A refused debit left an audit row describing an adjustment that never happened. An admin refund that `issue_refund` declined returned `200`. | Record and effect commit together (suspend, unsuspend, adjust, pricing, FX, flags, catalog); cancel and refund are recorded only after they succeed; a declined refund returns `409` | `test_a_refused_debit_leaves_no_admin_action`, `test_a_failed_audit_write_undoes_the_suspension`, `test_an_admin_refund_that_is_declined_says_so` |
| F-28 | Medium | Admin | A double-submitted wallet adjustment moved money twice | The console sends an `X-Idempotency-Key` per adjustment; the ledger key includes it | `test_a_resubmitted_adjustment_moves_money_once` |
| F-29 | Medium | Admin | Catalog managers could rewrite an offering's `provider_service_code` (what is bought upstream) and TTL; audits recorded only `is_enabled` | Only `is_enabled` is writable on offerings; every catalog edit records each changed field | `test_offering_edits_are_limited_to_enabling`, `test_catalog_edits_record_every_changed_field` |
| F-30 | Medium | Database | Invariants lived only in code: a payment could be `credited_at` without being `SUCCESS`; a DEPOSIT could debit; unknown statuses and zero refunds were storable | CHECK constraints for each (below) plus, on PostgreSQL, `balance_after = balance_before ± amount` on every ledger row | `test_db_constraints.py` (14), `test_the_database_rejects_a_ledger_row_whose_arithmetic_is_wrong` |
| F-31 | Low | Logging / privacy | JWTs and full phone numbers in free text (exception messages, reprs) were not redacted; verification codes and SMS text were kept forever | Both redacted wherever they appear; codes and SMS text are erased 30 days after the order (nightly task), and the Privacy Policy says so | `test_log_hygiene.py`: full journeys captured through the production formatter |
| F-32 | Low | Headers | The frontend sent no HSTS | `max-age=31536000; includeSubDomains` in production (no `preload`: that should be a deliberate decision) | Verified on a production build |
| F-33 | Low | Test tooling | Under threads, SQLite's deferred transactions deadlock ("database is locked") instead of queueing, which made flow-level concurrency tests impossible | The test backend opens transactions with `BEGIN IMMEDIATE`. This is a test-only shim and does not change production. | `test_concurrency_flows.py` (11) |

---

## Area by area

What was checked, and what holds up — not only what was broken.

**Authentication.** Argon2 hashing; httpOnly cookies with double-submit CSRF; identical
responses for wrong password and unknown email; hashed single-use reset tokens. Now with full
revocation (F-03, F-19). *Gap:* no 2FA — see O-4.

**Wallet accounting.** One writer (`post_entry`); append-only ledger with a per-wallet
sequence; `UNIQUE(wallet, idempotency_key)`; compare-and-set plus `SELECT FOR UPDATE` plus
`CHECK (balance >= 0)`; nightly reconciliation that reports drift instead of hiding it. No
defects found beyond F-08. A source-level test (`test_ledger_boundary.py`) fails if any file
other than `wallet/services.py` writes a balance.

Concurrency is covered at two levels. `test_concurrency.py` covers the ledger primitive, and
`test_concurrency_flows.py` covers whole flows with real threads behind a barrier:
- two simultaneous purchases with money for one: one order, one debit, no orphan order;
- a double-clicked purchase: one order;
- a burst of six purchases stops exactly at the balance;
- five simultaneous refunds of one order: one credit;
- five duplicate webhooks, and five different events for one payment: one credit each;
- six concurrent deposits into one wallet: all land and the sequence is contiguous;
- a deposit racing a purchase;
- a crash after the debit rolls everything back;
- a provider failure refunds in full.

`test_postgres.py` observes the row lock directly: a second writer blocks until the first
commits, then reads the committed balance. It also asserts `FOR UPDATE` in the wallet and
payment lock SQL and READ COMMITTED isolation. **These have only run on SQLite so far. The
PostgreSQL-only tests skip there, so they are unproven until O-1.**

**Payment webhooks.** Raw-byte HMAC-SHA512, constant-time compare, replay index,
late-reversal protection. The weakest area in both passes (F-01, F-02, F-07, F-13, F-20–F-22,
F-25).

Now proven end to end with real signed Paystack payloads:
- a missing signature, a signature made with another secret, a tampered amount and re-serialised JSON are all rejected;
- five identical deliveries credit once;
- an unknown reference credits nothing;
- a mock-provider payment cannot be settled through the Paystack route.

**The browser can never confirm a payment.** No endpoint accepts a status (`PUT`/`PATCH`/`POST` on
a payment returns 405). A deposit request that claims `status: SUCCESS` starts `PENDING`.
"Check again" only asks Paystack's own verify-transaction endpoint and does what Paystack
says (`test_refresh_asks_paystack_and_obeys_its_answer`).

**Provider abstraction.** TextVerified endpoints, auth scheme and state map are **all
blank**, and a test (`test_no_textverified_endpoint_is_invented`) fails if anyone fills one
in without the docs. An unconfigured TextVerified cannot take money: catalogue sync reports
an error and lists nothing, and an order that somehow reaches it is refunded
(`test_an_order_that_reaches_unconfigured_textverified_is_refunded`). A 429 is backed off,
never retried through; every call passes the call budget. Paystack uses its publicly
documented endpoints only; three market-specific values are marked `TODO(credentials)`.

**Authorization.** Swept, not spot-checked. From another account:
- 8 object endpoints return `404`;
- 4 list endpoints return nothing of another user's;
- 10 account endpoints reject anonymous callers.

That is `test_authorization_sweep.py`, 20 tests. The admin matrix
(`test_admin_matrix.py`) sends all 10 admin mutations as each of the four roles. Each role
without the permission gets `403` and leaves no audit row and no ledger row. Each role with
it succeeds and leaves exactly one audit row, attributed to that admin. One tightening (F-16).

**Rate limiting.** Two bypasses (F-04, F-05) and an availability flaw (F-12), all fixed.

**Logging.** Structured JSON with request ids; phone numbers masked; codes, tokens, keys and
passwords redacted in messages, structured fields and stored payloads. Over-redaction fixed
(F-14). No log call emits a code, token or unmasked phone number (source scan).

**Secrets management.** Nothing is committed yet (the repository has no commits).
`.gitignore` excludes every `.env`, and `.dockerignore` now excludes them from images (F-24).
A key-pattern scan finds only test placeholders and one docs placeholder. The frontend
exposes only `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_BRAND_NAME`.

`test_secret_exposure.py` plants canary values in every secret setting, then fetches all 34
readable customer and admin endpoints. No canary, password hash or token appears in any
response. Tokens never appear in login or refresh bodies, and the auth cookies are httpOnly.

Production refuses to boot on anything in F-26 as well as the first pass's guards. The
mock-verification guard is intact.

**Database transactions.** Money moves inside one transaction; provider calls sit outside
it; savepoints contain expected integrity errors; notifications are sent `on_commit`.

Isolation is PostgreSQL's default READ COMMITTED, which the design relies on. Correctness
does not depend on isolation because every balance change takes `SELECT … FOR UPDATE` on the
wallet row. A waiter then re-reads the committed row, and the compare-and-set catches anything
else.

Constraints added (F-30):
- `wallet_totals_non_negative`, `ledger_direction_matches_type`, `ledger_sequence_positive`;
- `payment_status_valid`, `payment_credited_only_when_successful`;
- `order_status_valid`, `refund_amount_positive`;
- `ledger_arithmetic_consistent` on PostgreSQL only.

Existing ones:
- non-negative balance and ledger balance;
- positive amounts;
- unique ledger key and sequence per wallet, one refund per order (OneToOne), unique payment reference, unique webhook event per provider;
- unique order idempotency key per user.

Foreign keys that hold money history use `PROTECT`. Hot paths are indexed (wallet +
created_at, status + created_at, provider + provider reference, status + expires_at).

**Refunds.** One refund per order (unique constraint), immutable ledger entry, admin refunds
capped at the order price with a mandatory reason. One defect (F-11).

**Error handling.** One error envelope; no stack traces or provider internals reach clients;
integrity errors become 409s. Webhook status codes corrected (F-07).

---

## Open items before going live

These cannot be finished inside the repository. Items 1–3 **block taking real money**.

| # | Item | Why it is open | Owner |
|---|---|---|---|
| O-1 | **Run the suite on PostgreSQL 16** | Only SQLite was available here. Docker Desktop cannot start because WSL has no distribution, and the local PostgreSQL 18 needs a password I did not have. SQLite has no row locks, so the concurrency tests used the compare-and-set path, not `SELECT FOR UPDATE`. The 5 PostgreSQL-only tests have never run. `.github/workflows/ci.yml` runs everything on Postgres 16 with `REQUIRE_POSTGRES=1`, which aborts if the database is anything else, and a separate step fails if the PostgreSQL tests were skipped. The repository has no remote and no commits, so the workflow has never run. | You: create the GitHub repository and push |
| O-2 | **Authorised verification provider** | TextVerified stays blank behind the interface until official documentation and a reselling authorisation exist. Until then run `VERIFICATION_PROVIDER=textverified`: the marketplace shows "not live yet" and nothing can be bought. | You + provider |
| O-3 | **Paystack go-live** | Confirm the three `TODO(credentials)` values, register the webhook URL, restrict it to Paystack's published IPs at the edge, then run the checklist in `PAYMENT_INTEGRATION.md` with test keys. | You |
| O-4 | **2FA for staff accounts** | A SUPER_ADMIN can adjust any balance. That power should need a second factor. Fields exist; no flow is built. Strongly recommended before launch. | Engineering |
| O-5 | **Error monitoring and alerting** | No Sentry (or equivalent) is wired. Alerts listed in `DEPLOYMENT.md` → Monitoring need somewhere to fire. Also restrict `/django-admin/` by network, or disable it. | Engineering / ops |
| O-6 | **Legal review, backup restore test** | Terms, AUP and Privacy Policy are drafts. A backup that has never been restored is a hope. | You + counsel |

Optional hardening: CSP violation reporting (`report-to`) to catch regressions in the field.

**CSP, verified on a production build** (`next build` + `next start`):
- all 25 routes return a nonce-based policy with `'strict-dynamic'` and no script `'unsafe-inline'`;
- every `<script>` on every route carries that response's nonce, and nonces differ per response;
- `connect-src` is the page's own origin plus the API origin;
- `frame-src 'none'`.

Payments are unaffected because none of the payment flow runs in the browser. The charge is
created server-side, and the customer approves the MoMo prompt on their phone. **If you ever
switch to Paystack's hosted checkout or inline popup, the CSP must be widened for it first.**

---

## Deployment settings introduced by this audit

| Setting | Production value | Effect |
|---|---|---|
| `TRUSTED_PROXY_COUNT` | `1` on Render | Client IP read from the right of `X-Forwarded-For` (F-04) |
| `JWT_SIGNING_KEY` | required, not `SECRET_KEY` | (F-17) |
| `WEBHOOK_PROVIDERS` | empty; list the old provider only during a switchover | Which webhook endpoints are live (F-01) |
| `VERIFICATION_PROVIDER` | `textverified` until authorised | Inert, sells nothing (F-09) |
| `ALLOW_MOCK_VERIFICATION_IN_PRODUCTION` | unset | Only for a non-public staging stack |
| `DB_SSLMODE` | `require` or stricter | Refuses to boot otherwise (F-26); `ALLOW_UNENCRYPTED_DATABASE=true` only for a private link you trust |
| `ALLOW_PAYSTACK_TEST_KEYS` | unset | Only for a non-public staging stack (F-26) |
| `VERIFICATION_DATA_RETENTION_DAYS` | `30` | Codes and SMS text erased after this (F-31) |

All are in `backend/.env.example`. `infrastructure/render.yaml` sets `TRUSTED_PROXY_COUNT`,
`DB_SSLMODE` and `VERIFICATION_PROVIDER`.

---

## Launch checklist: GO / NOT GO

**Verdict: NOT GO.** Nothing in the code blocks a launch. What blocks it is proof: the
PostgreSQL CI suite has not run (O-1), and there is no authorised verification provider to
sell (O-2).

| # | Gate | Status |
|---|---|---|
| 1 | Backend suite green on SQLite: 317 passed, 5 skipped (PostgreSQL-only), ruff clean, migrations complete | ✅ GO |
| 2 | **Backend suite green on PostgreSQL 16 in CI, 0 skipped** | ❌ **NOT GO**. Never run (O-1) |
| 3 | Frontend typecheck, lint and production build | ✅ GO |
| 4 | Critical and High security findings open | ✅ GO: 0 of 3 Critical, 0 of 9 High |
| 5 | Double-spend, duplicate-webhook, concurrent-refund and rollback tests | ✅ on SQLite · ❌ on PostgreSQL (gate 2) |
| 6 | Paystack webhook: signature, idempotency, reference, event and currency checks; browser cannot confirm | ✅ GO (proven with signed payloads) |
| 7 | Paystack go-live: 3 `TODO(credentials)` confirmed, webhook URL registered, IP allowlist at the edge, test-key rehearsal on staging | ❌ NOT GO (O-3) |
| 8 | Verification provider: official docs and reselling authorisation, adapter filled in from them | ❌ NOT GO (O-2). TextVerified stays inert; nothing can be sold |
| 9 | Refresh rotation, reuse detection, revocation, login throttling | ✅ GO |
| 10 | CSP on a production build, all routes | ✅ GO |
| 11 | Production refuses unsafe configuration (17 cases), mock verification refused | ✅ GO |
| 12 | Secrets: none in git, none in images, none in API responses or logs | ✅ GO. Rotate anything that was ever in a local `.env` before first use |
| 13 | Staff 2FA | ⚠️ Strongly recommended (O-4) |
| 14 | Error monitoring and alerting; `/django-admin/` restricted | ❌ NOT GO (O-5) |
| 15 | Legal review of Terms, AUP and Privacy; one backup restored end to end | ❌ NOT GO (O-6) |

**Order of work to reach GO:**
1. Push to GitHub and get gate 2 green.
2. Staging with Paystack test keys (`ALLOW_PAYSTACK_TEST_KEYS=true`, gate 7).
3. Monitoring and a backup restore (gates 14 and 15).
4. Legal review.
5. Live Paystack keys.

Verification numbers can go on sale only after gate 8, and adding them is a separate
change reviewed against the provider's documentation.

