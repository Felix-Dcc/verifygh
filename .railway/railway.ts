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

/**
 * The registrable domain everything sits under.
 *
 * Both halves of the platform share it deliberately. On `up.railway.app` they
 * were separate *sites* - that hostname is on the Public Suffix List - so the
 * auth cookie was third-party and needed SameSite=None to work at all. Under
 * one registrable domain the cookie is first-party and SameSite=Lax holds, so
 * it is no longer sent on cross-site requests.
 */
const ROOT_DOMAIN = "getverifygh.com";

/** The API's public domain. */
const API_DOMAIN = `api.${ROOT_DOMAIN}`;

/**
 * The frontend's public domain, and the bare domain beside it.
 *
 * Both serve the site. The apex was expected to redirect to www - Namecheap
 * has a URL redirect on it - but the ALIAS record wins, so the bare domain
 * reaches Railway directly.
 *
 * That matters for CORS, and it is worth stating because it caused a real
 * outage: only www was allowlisted, so anyone arriving at the bare domain sent
 * `Origin: https://getverifygh.com`, had every API call blocked, and saw
 * "Could not reach VerifyGH" with nothing wrong on either host. Whichever
 * hostname serves the app has to be an allowed origin.
 */
const WEB_DOMAIN = `www.${ROOT_DOMAIN}`;
const WEB_ORIGIN = `https://${WEB_DOMAIN}`;
const APEX_ORIGIN = `https://${ROOT_DOMAIN}`;

/**
 * The Railway-issued hostnames, kept alive alongside the custom ones.
 *
 * Still in ALLOWED_HOSTS and the CORS list because the Paystack *live* webhook
 * may still point at the old API host. Dropping them before that is repointed
 * would mean real payments arriving at a host Django refuses - money taken and
 * never credited. Remove once the webhook is confirmed on API_DOMAIN.
 */
const LEGACY_API_DOMAIN = "verifygh-production.up.railway.app";
const LEGACY_WEB_ORIGIN = "https://verifygh-web-production.up.railway.app";

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
    ALLOWED_HOSTS: `healthcheck.railway.app,${API_DOMAIN},${LEGACY_API_DOMAIN},\${{RAILWAY_PUBLIC_DOMAIN}}`,

    // Railway's edge is one proxy hop. The client IP is read that many hops
    // from the right of X-Forwarded-For; wrong here means either everyone
    // shares the proxy's IP or clients can forge theirs. Verify after the
    // first deploy (docs/DEPLOYMENT.md explains how).
    TRUSTED_PROXY_COUNT: "1",

    // The API and the app are on different domains, so the cookie is cross-site.
    AUTH_COOKIE_SECURE: "true",
    // Lax, not None: the site and the API are now first-party to each other,
    // so the cookie does not need to survive a cross-site request - and should
    // not be sent on one.
    AUTH_COOKIE_SAMESITE: "Lax",

    CELERY_TASK_ALWAYS_EAGER: "false",
    LOG_FORMAT: "json",
    LOG_LEVEL: "INFO",

    // Referral programme. Once read, the database row is the source of truth
    // and a super admin changes the bonus in the console.
    REFERRAL_PROGRAM_ENABLED: "true",
    REFERRAL_SIGNUP_BONUS_GHS: "5.00",
    REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS: "20",

    // Paystack in LIVE mode. ALLOW_PAYSTACK_TEST_KEYS is deliberately absent:
    // with it set, a key accidentally reverted to sk_test_ would boot happily
    // and credit every wallet for free. Its absence makes that combination
    // refuse to start.
    PAYMENT_PROVIDER: "paystack",

    // TextVerified is the primary provider (docs/PROVIDERS.md). The API refuses
    // to boot without TEXTVERIFIED_API_USERNAME and TEXTVERIFIED_API_KEY, and
    // nothing is sold through it until its written permission to resell is
    // recorded in Admin > Providers - its terms prohibit sharing numbers with
    // third parties. OnlineSim, the previous provider, is switched off.
    VERIFICATION_PROVIDER: "textverified",
    // 0 = no count limit. The TextVerified sync still stops at a 60-second
    // budget or its first 429, and resumes where it stopped next time.
    PROVIDER_CATALOG_LIMIT: "0",
    // The only country customers may browse or buy. The catalogue sync walks
    // only these, so Canada is neither synced nor sold.
    MARKETPLACE_COUNTRIES: "US",
    // Walked first, so these fill the catalogue and lead the listing.
    PROVIDER_PRIORITY_COUNTRIES: "US",
    // Our own restraint on upstream calls. TextVerified documents 429s but no
    // figures, so this stays generous and the adapter backs off on a 429.
    PROVIDER_RATE_LIMIT_PER_MINUTE: "300",

    // Verification and password-reset links are built from this, so it must be
    // the host a customer can actually open.
    FRONTEND_URL: WEB_ORIGIN,
    CORS_ALLOWED_ORIGINS: `${LEGACY_WEB_ORIGIN},${WEB_ORIGIN},${APEX_ORIGIN}`,
    CSRF_TRUSTED_ORIGINS: `${LEGACY_WEB_ORIGIN},${WEB_ORIGIN},${APEX_ORIGIN}`,

    // Transactional email. RESEND_API_KEY is a secret and lives in the
    // dashboard; with it set, the app configures Resend's documented SMTP
    // endpoint itself.
    //
    // getverifygh.com is verified in Resend - DKIM, SPF, the bounce MX and the
    // relay CNAME all pass - so mail reaches anyone, not just the account
    // owner. Sending from an unverified domain is rejected outright, so this
    // and the Resend domain have to move together.
    DEFAULT_FROM_EMAIL: `VerifyGH <no-reply@${ROOT_DOMAIN}>`,
    EMAIL_VERIFICATION_TTL_HOURS: "24",

    // A Turnstile token is only good if it was solved on our own pages.
    TURNSTILE_ALLOWED_HOSTNAMES: `${WEB_DOMAIN},${ROOT_DOMAIN}`,
    // Sign in with Google: register exactly this address as an authorised
    // redirect URI on the OAuth client (docs/GOOGLE_SIGN_IN.md).
    GOOGLE_OAUTH_REDIRECT_URI: `https://${API_DOMAIN}/api/v1/auth/google/callback/`,

    // --- set these in the Railway dashboard -----------------------------
    SECRET_KEY: preserve(),
    JWT_SIGNING_KEY: preserve(),
    // Left unset on purpose: a cookie domain of .up.railway.app would be
    // shared with every Railway app, and browsers reject it anyway. Set it
    // only once the API and app share a registrable domain.
    // Shared across www and api so one sign-in covers both. Safe here in a way
    // it never was on .up.railway.app, which every Railway app shares.
    AUTH_COOKIE_DOMAIN: `.${ROOT_DOMAIN}`,
    PAYSTACK_SECRET_KEY: preserve(),
    // TextVerified credentials: the account email and the API key from its
    // dashboard. Required - the API refuses to boot without them.
    TEXTVERIFIED_API_USERNAME: preserve(),
    TEXTVERIFIED_API_KEY: preserve(),
    TEXTVERIFIED_BASE_URL: preserve(),
    // Optional: the whsec_ secret from TextVerified's webhook settings.
    TEXTVERIFIED_WEBHOOK_SECRET: preserve(),
    // Cloudflare origin lock (docs/CLOUDFLARE.md): off until the DNS is on
    // Cloudflare, then report, then enforce. The secret is the value
    // Cloudflare's Transform Rule sets on X-VerifyGH-Origin.
    CLOUDFLARE_MODE: preserve(),
    CLOUDFLARE_ORIGIN_SECRET: preserve(),
    // Cloudflare Turnstile's secret key. Set, sign-in and sign-up need a token
    // Cloudflare confirms - so give verifygh-web its site key and redeploy it
    // first, or nobody can sign in (docs/CLOUDFLARE.md, step 5).
    TURNSTILE_SECRET_KEY: preserve(),
    // Brandfetch client ID for Admin > Logos (docs/SERVICE_LOGOS.md). It is in
    // every logo URL, so not a secret - but it is ours, so it lives here.
    BRANDFETCH_CLIENT_ID: preserve(),
    // Sign in with Google: both, or neither (docs/GOOGLE_SIGN_IN.md).
    GOOGLE_OAUTH_CLIENT_ID: preserve(),
    GOOGLE_OAUTH_CLIENT_SECRET: preserve(),
    EXCHANGE_RATE_API_KEY: preserve(),
    // Set this and verification emails start arriving. Without it the API
    // refuses to boot, rather than writing them to the container log where
    // nobody will ever read them.
    RESEND_API_KEY: preserve(),
    // Only for a non-Resend provider.
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
    // Declared here so applying this file cannot strip a domain that was
    // attached from the CLI. The Railway-issued hostname stays alongside it
    // until the Paystack live webhook is confirmed on API_DOMAIN.
    networking: {
      customDomains: { [API_DOMAIN]: {} },
      serviceDomains: { [LEGACY_API_DOMAIN]: {} },
    },
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
    // `npm install`, not `npm ci`: the lockfile is generated on Windows, and
    // npm omits other platforms' optional binaries from it (the wasm32 resolver
    // binaries behind eslint-config-next), so `npm ci` refuses to install on
    // Linux. Every dependency is pinned to an exact version, so this resolves
    // the same tree anyway. --include=dev because Tailwind, PostCSS and
    // TypeScript are devDependencies that `next build` needs.
    build: "npm install --include=dev --no-audit --no-fund && npm run build",
    // The package.json script pins port 3000. Railway assigns $PORT, and the
    // private network is IPv6, so both are overridden here.
    start: "npx next start -H :: -p $PORT",
    healthcheck: "/",
    healthcheckTimeout: 120,
    networking: {
      // Both hostnames are attached; both therefore need to be allowed origins.
      customDomains: { [WEB_DOMAIN]: {}, [ROOT_DOMAIN]: {} },
    },
    env: {
      // Compiled into the browser bundle at build time, so it must be the
      // API's public URL - not the private one, which a browser cannot reach.
      // Nothing secret belongs in a NEXT_PUBLIC_ variable.
      NEXT_PUBLIC_API_URL: `https://${API_DOMAIN}/api/v1`,
      NEXT_PUBLIC_BRAND_NAME: "VerifyGH",
      // Where the Railway-generated hostname redirects to; signing in cannot
      // work on that hostname (see frontend/src/middleware.ts).
      NEXT_PUBLIC_SITE_ORIGIN: `https://${WEB_DOMAIN}`,
      // Server-side only (read by middleware, never bundled for the browser):
      // the same origin lock as the API. See docs/CLOUDFLARE.md.
      CLOUDFLARE_MODE: preserve(),
      CLOUDFLARE_ORIGIN_SECRET: preserve(),
      // Public by design: the Turnstile site key. Setting it also allows
      // https://challenges.cloudflare.com in the Content-Security-Policy.
      NEXT_PUBLIC_TURNSTILE_SITE_KEY: preserve(),
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
