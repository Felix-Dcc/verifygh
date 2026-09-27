# VerifyGH

**Verification made simple.** A Ghana-focused payment and access layer for supported
phone-verification services. Users top up a wallet with Mobile Money in cedis and spend
that balance on verification numbers sourced from an authorised upstream provider.

No card. No crypto. No USD.

```
Mobile Money  ──►  VerifyGH wallet (GHS ledger)  ──►  authorised provider  ──►  number + code
   MTN                    double-entry                     official API
   Telecel                immutable                        no scraping
   AT Money               reconciled nightly                no ToS circumvention
```

---

## Status

The platform is **complete and runs end to end today** on mock providers — marketplace,
wallet, MoMo deposits, purchases, live order tracking, automatic refunds and the admin
console all work with no credentials and no real money.

| | |
|---|---|
| Backend | Django 5 + DRF, **317 tests passing** (+5 PostgreSQL-only, run in CI), ruff clean |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind, 26 routes, builds clean |
| Providers | `mock` by default; `paystack` and `textverified` adapters ready for credentials |

**What is not done:** live provider credentials, and the open items in
[docs/AUDIT.md](docs/AUDIT.md#open-items-before-going-live). See
[What you must supply](#what-you-must-supply).

---

## Quick start

Two terminals, about three minutes. Full detail in [docs/SETUP.md](docs/SETUP.md).

```bash
# 1. Backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # works as-is for development
python manage.py migrate
python manage.py seed_demo                           # rate, pricing rule, catalog, demo accounts
python manage.py runserver 8000
```

```bash
# 2. Frontend
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open <http://localhost:3000>. Sign in with the demo customer printed by `seed_demo`
(`kwame@example.com` / `VerifyGH-Demo-2026`), add money, and buy a number — the mock
providers simulate the whole journey including a signed payment webhook.

Admin console: <http://localhost:3000/admin> as `admin@verifygh.local`.

---

## Documentation

| Document | What is in it |
|---|---|
| [AUDIT.md](docs/AUDIT.md) | **Pre-production audit: 33 findings fixed; open items and the GO / NOT GO checklist** |
| [REFERRALS.md](docs/REFERRALS.md) | Referral programme and promotional credit: the two-bucket wallet, eligibility, anti-abuse |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, module map, the money path, state machines |
| [SETUP.md](docs/SETUP.md) | Local development, Celery, Postgres, seeding, troubleshooting |
| [API.md](docs/API.md) | Every endpoint, the error envelope, auth and idempotency |
| [SECURITY.md](docs/SECURITY.md) | Threat model, controls, financial integrity, disclosure |
| [PAYMENT_INTEGRATION.md](docs/PAYMENT_INTEGRATION.md) | Wiring a real MoMo aggregator, webhooks, going live |
| [EMAIL.md](docs/EMAIL.md) | Transactional email through Resend, verification tokens, the purchase gate |
| [PROVIDER_INTEGRATION.md](docs/PROVIDER_INTEGRATION.md) | Wiring an authorised verification provider |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Production topology, environment, migrations, monitoring |

---

## Repository layout

```
backend/            Django 5 + DRF + Celery
  config/           settings (base/dev/test/prod), urls, celery
  apps/
    common/         base models, error envelope, money, logging, throttles
    accounts/       User, roles, cookie JWT auth, email verification
    audit/          AuditLog, AdminAction, SuspiciousActivity
    wallet/         Wallet (cash + promotional buckets), immutable ledger
    referrals/      Referral codes, attribution, eligibility, rewards, risk flags
    payments/       Payment, webhooks, PaymentProvider interface + adapters
    catalog/        Country, Service, Provider, ProviderService, sync
    pricing/        PricingRule, ExchangeRate, the quote engine
    verification/   VerificationProvider interface + Mock/TextVerified
    orders/         Order state machine, refunds, Celery tasks
    notifications/  Notification model + channel abstraction
    adminapi/       Role-gated admin endpoints
  tests/            317 tests, money paths first

frontend/           Next.js 14 App Router
  src/app/          routes: marketing, auth, app, admin, legal
  src/components/   UI primitives, marketplace, orders, admin
  src/lib/          API client, types, formatting

docs/               the documents listed above
infrastructure/     Docker Compose, Dockerfile, Render blueprint
```

---

## The parts worth reading first

**`backend/apps/wallet/services.py`** — the ledger. The only code in the project that
writes a balance. Atomic, idempotent by database constraint, and safe against concurrent
spending.

**`backend/apps/payments/services.py`** — webhook handling. Nothing the browser sends can
credit a wallet; only a signature-verified callback or our own outbound reconciliation call.

**`backend/apps/orders/services.py`** — the purchase flow. Money moves inside one
transaction; the provider is called outside it; any failure refunds automatically.

**`backend/apps/pricing/engine.py`** — provider cost to customer price, fully explained and
frozen onto every order.

---

## Design decisions you may want to challenge

* **A prepaid wallet rather than pay-per-order.** MoMo collection has a per-transaction
  fee and a confirmation delay. Topping up once and spending several times is cheaper for
  the user and makes the purchase itself instant.
* **Prices include every fee.** No "plus charges" at checkout. The markup, the FX and the
  MoMo fee are all inside the number on the card.
* **Lettermarks instead of brand logos.** We are not licensed to redistribute third-party
  trademarks, and a consistent tile grid looks better than mismatched PNGs.
* **Codes are shown only where the provider agreement permits.** `DISPLAY_VERIFICATION_CODES`
  plus a per-provider flag; when off, the UI shows delivery status instead.

---

## What you must supply

Everything below is stubbed behind an interface with a working mock. Each is marked in code
with `TODO(credentials)`.

1. **Authorised verification provider** — an account or reseller arrangement that permits
   reselling, plus the official API documentation. See
   [PROVIDER_INTEGRATION.md](docs/PROVIDER_INTEGRATION.md).
2. **MoMo aggregator merchant account** — Paystack, Hubtel or Flutterwave keys, plus the
   **webhook URL registered in their dashboard**. See
   [PAYMENT_INTEGRATION.md](docs/PAYMENT_INTEGRATION.md).
3. **Exchange-rate feed** — an API key, or keep admin-entered manual rates.
4. **Transactional email** — SMTP or API credentials and a verified sending domain.
5. **Legal review** — the Terms, Acceptable Use Policy and Privacy Policy in
   `frontend/src/app/(legal)/` are drafts. Have Ghanaian counsel review them against the
   Data Protection Act, 2012 (Act 843) and your aggregator's merchant terms before taking
   real payments.

---

## Acceptable use

VerifyGH is built for legitimate verification needs and is positioned that way throughout.
It must not be used for fraud, impersonation, spam, evading bans or platform security, or
circumventing identity and KYC checks. Those limits are enforced in the product — accepting
the policy is a database-enforced precondition of purchase, and abuse signals are recorded
and actionable.

The provider integration uses official APIs only. There is no scraping, no browser
automation, no CAPTCHA handling and no rate-limit evasion anywhere in this codebase, and
the adapter layer has a hard call budget in front of it.
