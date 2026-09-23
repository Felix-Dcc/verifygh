# Deployment

## Topology

```
                    Cloudflare / CDN
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
   Vercel                              Railway (Render / AWS also fine)
   Next.js frontend                    ┌─────────────────────┐
   verifygh.com                        │ web (gunicorn)      │
                                       │ worker (celery)     │
                                       │ beat (celery beat)  │
                                       └──────────┬──────────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                              PostgreSQL       Redis        S3 (optional)
                              + backups        managed
                              (Railway)        (Railway)
```

Three backend processes, not one. The web process must never run scheduled work, and the
beat process must be a **single instance** — two beats means every periodic task runs twice.

---

## Environment

Start from `backend/.env.example`. Production additionally requires:

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=<64+ random bytes, never the dev value>
JWT_SIGNING_KEY=<separate from SECRET_KEY>
DEBUG=false

DATABASE_URL=postgres://user:pass@host:5432/verifygh
DB_SSLMODE=require
REDIS_URL=rediss://...

ALLOWED_HOSTS=api.verifygh.com
CORS_ALLOWED_ORIGINS=https://verifygh.com
CSRF_TRUSTED_ORIGINS=https://verifygh.com
FRONTEND_URL=https://verifygh.com

# Frontend and API are on different subdomains, so the cookie must be cross-site.
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=None
AUTH_COOKIE_DOMAIN=.verifygh.com

CELERY_TASK_ALWAYS_EAGER=false
LOG_FORMAT=json
LOG_LEVEL=INFO

# Proxy hops in front of Django (Railway: 1, Render: 1). The client IP for rate
# limits and audit logs is read this many hops from the RIGHT of X-Forwarded-For.
# Too low and every request looks like the proxy; too high (or unset with a
# proxy) and clients can forge their IP and walk past every rate limit.
TRUSTED_PROXY_COUNT=1

PAYMENT_PROVIDER=paystack
PAYSTACK_SECRET_KEY=sk_live_...
# Keep textverified until official docs + authorisation are in hand. Its
# endpoints are blank, so the catalogue stays empty and nothing can be bought.
# Production refuses to boot with `mock` - it would sell simulated numbers.
VERIFICATION_PROVIDER=textverified
TEXTVERIFIED_API_KEY=...
EXCHANGE_RATE_PROVIDER=api
EXCHANGE_RATE_API_KEY=...
EXCHANGE_RATE_API_URL=...
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=...
```

> **Cookie domains.** If the API is on `api.verifygh.com` and the app on `verifygh.com`,
> set `AUTH_COOKIE_DOMAIN=.verifygh.com` and `SameSite=None`. If you put the API behind the
> same origin via a path proxy, keep `SameSite=Lax` — it is strictly safer.

`config/settings/prod.py` **refuses to boot** if:

* a required variable is missing (including `JWT_SIGNING_KEY`, which must differ from
  `SECRET_KEY`),
* `SECRET_KEY` still holds a development value,
* `PAYMENT_PROVIDER=mock`, or Paystack is selected with no secret key,
* `WEBHOOK_PROVIDERS` includes `mock` (its signing secret is public),
* `VERIFICATION_PROVIDER=mock`, unless `ALLOW_MOCK_VERIFICATION_IN_PRODUCTION=true` is set
  for a non-public staging stack,
* `SECRET_KEY` or `JWT_SIGNING_KEY` is shorter than 50 characters, or they are equal,
* `PAYSTACK_SECRET_KEY` is a public key (`pk_…`) or a test key (`sk_test_…`). A test key is
  allowed only with `ALLOW_PAYSTACK_TEST_KEYS=true`, for staging,
* `TRUSTED_PROXY_COUNT` is not set explicitly,
* `DB_SSLMODE` is weaker than `require`, unless `ALLOW_UNENCRYPTED_DATABASE=true`,
* `FRONTEND_URL` or any `CORS_ALLOWED_ORIGINS` entry is not `https://`.

Production never reads a `.env` file. Every value must come from the deploy environment.
The repository-root `.dockerignore` keeps `.env` files out of images.

`tests/test_startup_safety.py` boots the production settings from a safe baseline, then
changes one thing at a time and checks that each unsafe case refuses. CI also asserts that
production refuses to boot without secrets. Neither guard can silently regress.

---

## Backend and database — Railway

`.railway/railway.ts` describes the whole Railway project: **PostgreSQL, Redis, and the
three backend processes** (web, Celery worker, Celery beat). It is Railway
*Infrastructure as Code*; `railway.json` / `railway.toml` is deprecated and stops being
read on **2026-12-01**.

Railway never reads this file during a deploy. You apply it from your machine or from CI:

```bash
npm install            # the `railway` SDK that .railway/railway.ts imports
railway login
railway link           # choose the project and environment
railway config plan    # review every change first
railway config apply
```

`plan` only reads. `apply` shows the same plan and waits for confirmation, and marks
anything destructive.

### Root directory

Every service builds from **`backend/`**. `.railway/railway.ts` sets that
(`rootDirectory: "backend"`), but a service created by hand in the dashboard builds from the
repository root instead - where it finds the `package.json` that exists only for the Railway
SDK, decides the project is a Node app, and fails with "No start command detected". If you
see that, set **Settings → Source → Root Directory** to `backend`, or apply the IaC.

### Set the secrets first

Everything marked `preserve()` in the file must exist in Railway before the first deploy —
`preserve()` means "keep whatever is already set", not "invent one". Production refuses to
boot when any is missing and names it in the logs.

```bash
railway variables --set SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')"
railway variables --set JWT_SIGNING_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')"
railway variables --set FRONTEND_URL="https://verifygh.com"
railway variables --set CORS_ALLOWED_ORIGINS="https://verifygh.com"
railway variables --set CSRF_TRUSTED_ORIGINS="https://verifygh.com"
railway variables --set AUTH_COOKIE_DOMAIN=".verifygh.com"
railway variables --set PAYMENT_PROVIDER="paystack"
railway variables --set PAYSTACK_SECRET_KEY="sk_live_..."
```

The two keys must differ and be at least 50 characters; `prod.py` enforces both.

### Six things Railway does differently

**1. Healthchecks come from `healthcheck.railway.app`.** Django answers `400 DisallowedHost`
to a hostname that is not in `ALLOWED_HOSTS`, so every deploy would fail its healthcheck.
The file sets `ALLOWED_HOSTS=healthcheck.railway.app,${{RAILWAY_PUBLIC_DOMAIN}}`. Add your
custom API domain to that list when you attach one.

**2. Migrations run in `preDeploy`, never in the build.** Railway's private network is
runtime-only: a build cannot reach the database. The pre-deploy command *can*, it has the
service variables, and a failure stops the deployment — so a broken migration never reaches
live traffic. `collectstatic` stays in the build and deliberately runs under
`config.settings.base`, because static files need no production secrets.

**3. Bind `[::]`, not `0.0.0.0`.** The private network is IPv6 (environments created before
16 October 2025 are IPv6-only). A dual-stack socket on Linux accepts IPv4 as well, so
`--bind [::]:$PORT` works for both the public edge and internal traffic.

**4. `TRUSTED_PROXY_COUNT=1`.** Railway's edge is one proxy hop. This governs the client IP
used by rate limits, audit logs and device fingerprints — too low and every user looks like
the proxy, too high and they can forge it. Verify it once after the first deploy: sign in
with a wrong password from your phone, then check the recorded IP in
`/api/v1/admin/audit/`. If it is a Railway internal address rather than your own, the
count is wrong.

**5. Pin the Python version.** Railpack defaults to the newest Python, which is ahead of
what this project is tested on and ahead of some pinned wheels - `psycopg[binary]==3.2.1`
has no 3.13 build, and the install fails outright. `backend/.python-version` and
`RAILPACK_PYTHON_VERSION` both say **3.11**, matching CI and the local virtualenv.
Production should never be the first place a dependency meets a new interpreter.

**6. The database is SSL-enabled.** Railway's Postgres image supports TLS, so
`DB_SSLMODE=require` works as-is and the production guard needs no exception. Traffic
between services is also Wireguard-encrypted.

### After the first apply

1. **Generate a domain** for `verifygh-api` (Settings → Networking), or attach your own.
2. **Create the first admin**: `railway run --service verifygh-api python manage.py createsuperuser`.
3. **Sync the catalogue**: `railway run --service verifygh-api python manage.py sync_catalog`.
   It reports errors and lists nothing while the verification provider is unconfigured —
   that is the intended, inert state.
4. **Point Paystack's webhook** at `https://<your-api-domain>/api/v1/payments/webhooks/paystack/`.
5. **Turn on Railway's backups** for the Postgres service, then **restore one into a scratch
   project** and run `reconcile_wallets` against it. An untested backup is a hope.

Do **not** run `seed_demo` in production. It skips demo accounts when `DEBUG=false`, but it
also seeds a placeholder exchange rate you do not want.

### Scaling notes

`verifygh-beat` must stay at **one replica**. Two beats run every scheduled task twice: two
catalogue syncs, two reconciliations, two referral sweeps. The web service can scale
horizontally; the worker can too.

Railway's Postgres is a single instance unless you convert it to the Patroni-backed
high-availability cluster. For a system holding customer balances, plan that conversion (or
an external managed database) before volume grows.

---

## Backend — Render (alternative)

`infrastructure/render.yaml` is a working blueprint: web, worker, beat and Redis, with the
database supplied separately. Kept for anyone deploying outside Railway.

```bash
render blueprint launch     # or point the dashboard at the repo
```

Then set the secrets marked `sync: false` in the dashboard, and run once from a shell:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py sync_catalog
```

Do **not** run `seed_demo` in production — it skips demo accounts when `DEBUG=false`, but
it also seeds a placeholder exchange rate you do not want.

### Manual (any host)

```bash
# Build
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Web
gunicorn config.wsgi:application \
  --bind 0.0.0.0:$PORT --workers 3 --threads 2 \
  --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 \
  --access-logfile - --error-logfile -

# Worker
celery -A config worker -l info --concurrency=4 --max-tasks-per-child=200

# Beat — exactly one instance
celery -A config beat -l info
```

`--max-requests` recycles workers to bound any slow memory growth. `acks_late` is on, so a
worker dying mid-task means the task is redelivered rather than lost.

---

## Frontend — Vercel

```bash
cd frontend
vercel --prod
```

Root directory `frontend`, framework Next.js, and one environment variable:

```
NEXT_PUBLIC_API_URL=https://api.verifygh.com/api/v1
NEXT_PUBLIC_BRAND_NAME=VerifyGH
```

Every page is rendered per request. That is required by the nonce-based
Content-Security-Policy: a page prerendered at build time has no request and therefore
no nonce, and the browser would block all of its scripts. Do not add
`export const dynamic = "force-static"` or `generateStaticParams` to any route without
changing the CSP strategy first. Verify a production build with `next build && next
start` — `next dev` renders on demand and will not show this failure.

**Everything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle.** No secret may
ever go in the frontend environment. There is no server-side secret in this frontend at
all — it talks to the API as the browser does.

---

## Docker

`infrastructure/docker-compose.yml` brings up the whole stack:

```bash
cd infrastructure
cp ../backend/.env.example ../backend/.env
docker compose up --build
```

Postgres, Redis, web, worker and beat. Suitable for staging or a self-hosted VPS; for
production prefer a managed database so you get backups and point-in-time recovery without
building them.

---

## Deployment order

Order matters, because the ledger must never be ambiguous.

1. **Back up the database**, and confirm the backup restores.
2. **Migrate** before deploying code that depends on the new schema. Every migration here is
   additive; if you add a destructive one, split it across two releases.
3. **Deploy the web process.**
4. **Deploy worker and beat.** Drain the old worker first (`--soft-time-limit` handles
   in-flight tasks), so a task is not half-executed by two code versions.
5. **Smoke test** — see below.

### Zero-downtime notes

* Never remove a ledger, payment or order field in the same release that stops writing it.
* `acks_late=True` means a task interrupted by a deploy is redelivered. Every task here is
  idempotent, which is what makes that safe.
* Beat must be stopped before its replacement starts. Two beats double every sweep.

---

## Post-deploy smoke test

```bash
curl https://api.verifygh.com/health/                     # {"status":"ok","database":true}
curl https://api.verifygh.com/api/v1/catalog/health/      # {"ready":true,...}
```

Then, signed in as an admin, check `/admin/health/`:

- [ ] Verification provider: **not** mock, reachable
- [ ] Payment provider: **not** mock, reachable
- [ ] Exchange rate configured and recent
- [ ] Active pricing rules ≥ 1
- [ ] Unprocessed webhooks = 0

And end to end, with a real GHS 1 deposit:

- [ ] Deposit prompt arrives on a handset
- [ ] Approving it credits the wallet exactly once
- [ ] A purchase assigns a number
- [ ] `reconcile_wallets` exits 0

---

## Monitoring

**Page someone for:**

| Signal | Why |
|---|---|
| `reconcile_wallets` exits non-zero | A balance has drifted from its ledger |
| `unprocessed_webhooks > 0` | A customer may have paid without being credited |
| `webhook_signature_invalid` spike | Someone is probing, or your secret rotated badly |
| `/health/` returning 503 | Database unreachable |
| Beat not running | Nothing expires, nothing refunds, failed webhooks are not replayed |
| `payment_overpayment_held` | A deposit is waiting on a human decision |
| `webhook_provider_mismatch` | Someone tried to settle a payment with another provider's callback |

**Watch, but do not page:**

`provider_call` latency, `PROVIDER_BUDGET_EXCEEDED`, order failure rate (visible on the
admin dashboard), `exchange_rate_stale`, authentication failure rate.

Logs are JSON in production (`LOG_FORMAT=json`) with a request id on every line, and a
redaction filter that strips anything credential-shaped. Ship them somewhere searchable —
the first question in any payment dispute is "what happened to reference X", and that should
take seconds.

---

## Backups

* Postgres: turn on Railway's **Backups** for the database service. The ledger is the
  business; losing a day of it is not recoverable by any other means.
* Rehearse the restore in a **scratch project**: restore a backup into it, point a staging
  backend at it, and run `reconcile_wallets`, which must report zero drift.
* **Test a restore before launch, and quarterly after.** An untested backup is a hope.
* Redis holds cache and queue state only. Losing it costs you in-flight mock state and a
  cache warm-up, not money.

---

## Scaling

The first bottleneck will be provider API latency, not your database.

| Symptom | Move |
|---|---|
| Slow order fulfilment | Raise worker concurrency; check `PROVIDER_RATE_LIMIT_PER_MINUTE` against your contract |
| Slow marketplace | It is cached for 45s; raise it, or move the cache to Redis if not already |
| Wallet lock contention | Real Postgres row locks scale far past SQLite. Watch `ledger_lock_contention_retry`. |
| Many active orders | Raise `POLL_BATCH_SIZE`, or shard the poll task by order-id hash |

The wallet is per-user, so lock contention is bounded by a single user's concurrency, not by
total traffic. This scales further than it looks.

---

## Rollback

1. Redeploy the previous image.
2. **Do not roll migrations back** unless you are certain nothing has written to the new
   schema. Rolling back a migration that touched the ledger is how you lose money.
3. If a bad release credited or debited incorrectly, do **not** edit rows. Post
   compensating `ADJUSTMENT` entries with a reason — the ledger stays append-only and the
   mistake stays visible.
