/**
 * VerifyGH on Railway: PostgreSQL, Redis, and the three backend processes.
 *
 * Railway Infrastructure as Code. `railway.json` / `railway.toml` (Config as
 * Code) is deprecated and stops being read on 2026-12-01, so this is the
 * supported way to describe the project.
 *
 * Apply it yourself - Railway never reads this file during a deploy:
 *
 *     npm install                 # installs the `railway` SDK this file imports
 *     railway login
 *     railway link                # pick the project and environment
 *     railway config plan         # review
 *     railway config apply
 *
 * Secrets are declared as preserve(), which means "keep whatever is set in
 * Railway". They are never written here. Set them in the dashboard, or with
 * `railway variables --set`. Production refuses to boot if any is missing, and
 * says which - see docs/DEPLOYMENT.md.
 *
 * Five services: the Next.js frontend, the Django API, a Celery worker, a
 * Celery beat scheduler, and the Postgres and Redis they share.
 */

import {
  type VariableValue,
  defineRailway,
  github,
  group,
  postgres,
  preserve,
  project,
  redis,
  service,
} from "railway/iac";

const REPO = "Felix-Dcc/verifygh";

/** The API's public domain. Swap this for your own when you attach one. */
const API_DOMAIN = "verifygh-production.up.railway.app";

/**
 * The frontend's public domain.
 *
 * Note for go-live: these two are different *sites*, because `up.railway.app`
 * is a public suffix. The auth cookie is therefore a third-party cookie, which
 * browsers increasingly block. Put both behind one registrable domain
 * (app.verifygh.com and api.verifygh.com) before taking real customers, and
 * set AUTH_COOKIE_DOMAIN to `.verifygh.com` then - never to `.up.railway.app`,
 * which is shared with every other Railway app.
 */
const WEB_DOMAIN = "verifygh-web-production.up.railway.app";
const WEB_ORIGIN = `https://${WEB_DOMAIN}`;

/** Everything Django needs. The three processes share one configuration. */
function backendEnv(databaseUrl: VariableValue, redisUrl: VariableValue) {
  return {
    DJANGO_SETTINGS_MODULE: "config.settings.prod",

    // Railpack defaults to the newest Python (3.13 at the time of writing).
    // Pin the version the test suite and CI actually run, so production is
    // never the first place a dependency meets a new interpreter - psycopg's
    // pinned build has no 3.13 wheel, for one. backend/.python-version says
    // the same thing for anyone building outside this file.
    RAILPACK_PYTHON_VERSION: "3.11",

    // Railway's Postgres image is SSL-enabled, so the connection is encrypted
    // even inside the private network. Production refuses anything weaker.
    DATABASE_URL: databaseUrl,
    DB_SSLMODE: "require",
    DB_POOL_MODE: "session",
    REDIS_URL: redisUrl,

    // Healthchecks arrive as healthcheck.railway.app; without it here Django
    // answers 400 DisallowedHost and every deploy fails its healthcheck.
    ALLOWED_HOSTS: `healthcheck.railway.app,${API_DOMAIN},\${{RAILWAY_PUBLIC_DOMAIN}}`,

    // Railway's edge is one proxy hop. The client IP is read that many hops
    // from the right of X-Forwarded-For; wrong here means either everyone
    // shares the proxy's IP or clients can forge theirs. Verify after the
    // first deploy (docs/DEPLOYMENT.md explains how).
    TRUSTED_PROXY_COUNT: "1",

    // The API and the app are on different domains, so the cookie is cross-site.
    AUTH_COOKIE_SECURE: "true",
    AUTH_COOKIE_SAMESITE: "None",

    CELERY_TASK_ALWAYS_EAGER: "false",
    LOG_FORMAT: "json",
    LOG_LEVEL: "INFO",

    // Inert until an authorised provider is configured: the adapter's
    // endpoints are blank, so nothing is listed and nothing can be sold.
    VERIFICATION_PROVIDER: "textverified",

    // Referral programme. Once read, the database row is the source of truth
    // and a super admin changes the bonus in the console.
    REFERRAL_PROGRAM_ENABLED: "true",
    REFERRAL_SIGNUP_BONUS_GHS: "5.00",
    REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS: "20",

    FRONTEND_URL: WEB_ORIGIN,
    CORS_ALLOWED_ORIGINS: WEB_ORIGIN,
    CSRF_TRUSTED_ORIGINS: WEB_ORIGIN,

    // --- set these in the Railway dashboard -----------------------------
    SECRET_KEY: preserve(),
    JWT_SIGNING_KEY: preserve(),
    // Left unset on purpose: a cookie domain of .up.railway.app would be
    // shared with every Railway app, and browsers reject it anyway. Set it
    // only once the API and app share a registrable domain.
    AUTH_COOKIE_DOMAIN: preserve(),
    PAYMENT_PROVIDER: preserve(),
    PAYSTACK_SECRET_KEY: preserve(),
    TEXTVERIFIED_API_KEY: preserve(),
    TEXTVERIFIED_BASE_URL: preserve(),
    EXCHANGE_RATE_API_KEY: preserve(),
    EMAIL_HOST: preserve(),
    EMAIL_HOST_USER: preserve(),
    EMAIL_HOST_PASSWORD: preserve(),
  };
}

/**
 * Install dependencies and collect static files.
 *
 * collectstatic deliberately runs under the *base* settings: the build has no
 * private network (Railway builds cannot reach the database), and static files
 * have nothing to do with production secrets. Migrations run in preDeploy,
 * which does have the network.
 */
const BUILD = [
  "pip install -r requirements.txt",
  "DJANGO_SETTINGS_MODULE=config.settings.base python manage.py collectstatic --noinput",
].join(" && ");

const source = github(REPO, { rootDirectory: "backend" });

export default defineRailway(() => {
  const db = postgres("Postgres");
  const cache = redis("Redis");
  const env = backendEnv(db.env.DATABASE_URL, cache.env.REDIS_URL);

  // Named to match the service already in the project, so applying adopts it
  // (keeping its variables and domain) instead of replacing it.
  const api = service("verifygh", {
    source,
    build: BUILD,
    // Runs between build and deploy, with the private network and the service
    // variables. A failure here stops the deployment, so a bad migration never
    // reaches live traffic.
    preDeploy: "python manage.py migrate --noinput",
    // Bind [::] rather than 0.0.0.0: Railway's private network is IPv6, and
    // on Linux a dual-stack socket accepts IPv4 too.
    start: [
      "gunicorn config.wsgi:application --bind [::]:$PORT",
      "--workers 3 --threads 2 --timeout 60 --graceful-timeout 30",
      "--max-requests 1000 --max-requests-jitter 100",
      "--access-logfile - --error-logfile -",
    ].join(" "),
    healthcheck: "/health/",
    healthcheckTimeout: 120,
    env,
  });

  const worker = service("verifygh-worker", {
    source,
    build: BUILD,
    start: "celery -A config worker -l info --concurrency=4 --max-tasks-per-child=200",
    env,
  });

  // Exactly one replica, always. Two beats run every scheduled task twice -
  // two catalogue syncs, two reconciliations, two referral sweeps.
  const beat = service("verifygh-beat", {
    source,
    build: BUILD,
    start: "celery -A config beat -l info",
    replicas: 1,
    env,
  });

  const web = service("verifygh-web", {
    source: github(REPO, { rootDirectory: "frontend" }),
    // --include=dev is not optional: Tailwind, PostCSS and TypeScript are
    // devDependencies, and `next build` needs all three. A production install
    // would drop them and fail at the CSS step.
    build: "npm ci --include=dev && npm run build",
    // The package.json script pins port 3000. Railway assigns $PORT, and the
    // private network is IPv6, so both are overridden here.
    start: "npx next start -H :: -p $PORT",
    healthcheck: "/",
    healthcheckTimeout: 120,
    env: {
      // Compiled into the browser bundle at build time, so it must be the
      // API's public URL - not the private one, which a browser cannot reach.
      // Nothing secret belongs in a NEXT_PUBLIC_ variable.
      NEXT_PUBLIC_API_URL: `https://${API_DOMAIN}/api/v1`,
      NEXT_PUBLIC_BRAND_NAME: "VerifyGH",
    },
  });

  return project("verifygh", {
    resources: [
      group("Frontend", [web]),
      group("Backend", [api, worker, beat]),
      group("Data", [db, cache]),
    ],
  });
});
