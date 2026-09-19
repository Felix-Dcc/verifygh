# Local development

Everything runs without a single credential. The mock payment and verification providers
simulate the whole product, including cryptographically signed webhooks, so the code path
you exercise in development is the code path that runs in production.

## Requirements

| | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| Node | 18+ | 20 or 22 recommended |
| PostgreSQL | 15+ | Optional locally — SQLite is the default |
| Redis | 7+ | Optional locally — only needed for Celery |

---

## Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt

cp .env.example .env               # the defaults are development-ready
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 8000
```

`seed_demo` creates the four things a marketplace cannot function without, and is safe to
re-run:

* a USD/GHS exchange rate (a development placeholder — production uses a feed),
* a global default pricing rule (20% markup, 2% payment fee, 3% risk buffer),
* the provider catalogue, synced from the mock provider (80 offerings),
* demo accounts, **only when `DEBUG=true`**:

```
admin : admin@verifygh.local / VerifyGH-Demo-2026
user  : kwame@example.com    / VerifyGH-Demo-2026
```

Check it is alive:

```bash
curl http://localhost:8000/health/
curl http://localhost:8000/api/v1/catalog/health/
```

The second should report `"ready": true`. If it does not, it tells you which of the
provider, exchange rate or catalogue is missing.

---

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

<http://localhost:3000>.

`.env.local` holds only `NEXT_PUBLIC_API_URL` and the brand name. **Never put a secret in
it** — everything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle.

---

## Driving the mock providers

### Payments

A deposit puts the payment in `PENDING` and waits, exactly as a real MoMo prompt would.
Nothing the browser does can credit the wallet. To complete it you send a webhook, the same
way the aggregator will:

```bash
cd backend
python - <<'PY'
import django, os, urllib.request
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()
from apps.payments.models import Payment
from apps.payments.mock import build_webhook

payment = Payment.objects.filter(status__in=["PENDING", "PROCESSING"]).latest("created_at")
raw, headers = build_webhook(reference=payment.reference, amount=str(payment.amount))
request = urllib.request.Request(
    "http://localhost:8000/api/v1/payments/webhooks/mock/",
    data=raw, headers={"Content-Type": "application/json", **headers}, method="POST")
print(urllib.request.urlopen(request).read().decode())
PY
```

`build_webhook` signs with a real HMAC, so this exercises signature verification rather
than bypassing it. Send it five times — the wallet is credited once and the rest answer
`{"status": "duplicate"}`.

The **Check again** button on the waiting screen does the same job the other way round: it
asks the provider directly (`fetch_charge`), which is the reconciliation path that rescues
a dropped callback.

Force outcomes in tests with `apps.payments.mock.force_outcome("FAIL" | "TIMEOUT" |
"REJECT_AT_INITIATION" | None)`.

### Verification

The mock provider picks a scenario per order, weighted towards success:

| Scenario | Weight | What happens |
|---|---|---|
| `HAPPY` | 80% | Number assigned, code arrives ~8s later |
| `SLOW_CODE` | 10% | Code arrives after ~45s — exercises the waiting UI |
| `NO_CODE` | 5% | Number assigned, nothing arrives, expires, auto-refund |
| `NO_STOCK` | 3% | Provider has no number, order fails, immediate refund |
| `PROVIDER_ERR` | 2% | Provider call raises, order fails, immediate refund |

Pin one with `apps.verification.mock.force_scenario("NO_CODE")`, and skip the wait with
`fast_forward(provider_order_id, seconds)`.

### Why orders progress without a Celery worker

The live-status endpoint asks the provider itself when an order is genuinely waiting and we
have not asked recently, bounded by a per-order cooldown (`ORDER_POLL_SECONDS`). The Celery
sweep still covers users who close the tab. So a developer with no worker running sees
orders move, and a provider never sees more than one call per order per cooldown.

---

## Celery (optional locally)

`CELERY_TASK_ALWAYS_EAGER=true` in dev runs tasks inline, which is enough for everything
except the scheduled sweeps. To run them for real:

```bash
redis-server                                            # or: docker run -p 6379:6379 redis:7

cd backend
celery -A config worker -l info --pool=solo             # --pool=solo on Windows
celery -A config beat -l info                           # in another terminal
```

Set `CELERY_TASK_ALWAYS_EAGER=false` and `REDIS_URL=redis://127.0.0.1:6379/0`.

The beat schedule (see `config/celery.py`):

| Task | Every | Purpose |
|---|---|---|
| `poll_active_orders` | 10s | Ask the provider about orders that are waiting |
| `expire_stale_orders` | 60s | Expire and refund orders past their TTL |
| `expire_stale_payments` | 60s | Close unapproved prompts — **after** asking the provider |
| `refresh_exchange_rate` | 6h | Append a fresh FX rate |
| `sync_provider_catalog` | 3h | Refresh services, costs and availability |
| `reconcile_wallets` | daily 02:30 | Re-derive every balance from the ledger |

---

## PostgreSQL

SQLite is the default and is fine for feature work. Use Postgres when you care about
concurrency behaviour, because SQLite has no row-level locking:

```bash
docker run --name verifygh-db -e POSTGRES_PASSWORD=verifygh \
  -e POSTGRES_DB=verifygh -p 5432:5432 -d postgres:16
```

```bash
# backend/.env
DATABASE_URL=postgres://postgres:verifygh@localhost:5432/verifygh
```

Then `python manage.py migrate`.

---

## Tests

```bash
cd backend
pytest                                   # 150 tests
pytest tests/test_concurrency.py -v      # the double-spend tests
pytest tests/test_payments.py -v         # webhook replay and signature tests
pytest --cov=apps --cov-report=term-missing
```

The concurrency tests run real threads against real connections. On SQLite the test
database is a file with a busy timeout so they can serialise; on Postgres the row lock does
the work. Either way they assert the same invariant.

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

---

## Useful commands

```bash
python manage.py reconcile_wallets            # re-derive every balance; exits 1 on drift
python manage.py reconcile_wallets --json     # machine-readable
python manage.py sync_catalog                 # refresh the catalogue from the provider
python manage.py createsuperuser              # a real admin, for non-DEBUG environments
python manage.py seed_demo --no-accounts      # seed data without demo credentials
```

---

## Troubleshooting

**`catalog/health/` says `ready: false`** — run `python manage.py seed_demo`. It will tell
you whether the provider, the rate or the pricing rule is missing.

**Sign-in works but every write returns 401** — the CSRF cookie is not reaching the API.
Check `CORS_ALLOWED_ORIGINS` includes your frontend origin exactly, and that the frontend
calls the API on `localhost` (not `127.0.0.1`) if the cookie was set on `localhost`.

**Orders stay `PROCESSING` after restarting the server** — the mock provider keeps its state
in the local-memory cache, which dies with the process. Place a new order. (Set `REDIS_URL`
to make mock state survive restarts.)

**`No exchange rate has been configured`** — nothing can be priced. Add one in the admin
console under Catalog → Exchange rates, or re-run `seed_demo`.

**Concurrency tests fail with "database is locked"** — you are on SQLite without the test
settings. Run them via `pytest`, which uses `config.settings.test`.
