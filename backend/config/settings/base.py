"""Base settings shared by every environment.

Anything secret is read from the environment. Nothing secret has a usable
default: dev-only fallbacks exist, but `config.settings.prod` refuses to boot
if a real value is missing.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]

# A .env file is a development convenience. In production every value must come
# from the deploy environment: a stray .env in an image would otherwise fill in
# whatever the operator forgot to set - with development values.
if not os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".prod"):
    load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key, default)
    return value.strip() if isinstance(value, str) else value


def env_bool(key: str, default: bool = False) -> bool:
    raw = env(key)
    if raw is None or raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    raw = env(key)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def env_list(key: str, default: str = "") -> list[str]:
    raw = env(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY", "dev-insecure-do-not-use-in-production")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    # Refresh tokens are revocable: rotation blacklists the old token, so a
    # stolen refresh token cannot be replayed after the victim next refreshes.
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    # local
    "apps.common",
    "apps.accounts",
    "apps.audit",
    "apps.wallet",
    "apps.catalog",
    "apps.pricing",
    "apps.verification",
    "apps.payments",
    "apps.orders",
    "apps.numbers",
    "apps.funding",
    "apps.notifications",
    "apps.adminapi",
    "apps.referrals",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestContextMiddleware",
    # Before anything that does work: an unverified request in enforce mode
    # stops here.
    "apps.common.middleware.CloudflareOriginMiddleware",
    "apps.common.security.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------


def database_from_url(url: str) -> dict:
    """Minimal DATABASE_URL parser (postgres / sqlite) with no extra dependency."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme in {"sqlite", "sqlite3"}:
        name = parsed.path or "/db.sqlite3"
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name.lstrip("/") or "db.sqlite3"}
    if parsed.scheme not in {"postgres", "postgresql", "psql"}:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")
    options = {
        "sslmode": env("DB_SSLMODE", "prefer"),
        # Fail fast instead of hanging a worker when the database is unreachable.
        "connect_timeout": env_int("DB_CONNECT_TIMEOUT", 10),
    }
    if env("DB_SSLROOTCERT"):
        # The CA bundle to verify the server against, for sslmode=verify-full.
        options["sslrootcert"] = env("DB_SSLROOTCERT")

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        "OPTIONS": options,
    }

    # DB_POOL_MODE=transaction when connecting through a transaction-mode
    # pooler such as PgBouncer. Each transaction may land on a different server
    # connection, so nothing may outlive one:
    #   * server-side cursors (QuerySet.iterator(), used by the nightly wallet
    #     reconciliation) would vanish between fetches;
    #   * prepared statements would be missing on the next backend. Django uses
    #     client-side binding by default, so this is a guard, not a fix;
    #   * persistent client connections buy nothing - the pooler already pools.
    # Row locks are unaffected: SELECT ... FOR UPDATE lives inside one
    # transaction, which the pooler keeps on one server connection.
    if env("DB_POOL_MODE", "session") == "transaction":
        config["DISABLE_SERVER_SIDE_CURSORS"] = True
        config["CONN_MAX_AGE"] = 0
        options["prepare_threshold"] = None
    return config


DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {"default": database_from_url(DATABASE_URL)}
else:
    # Dev convenience only. Production settings require DATABASE_URL.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2 first: slow by design, and the default hasher for new passwords.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# --------------------------------------------------------------------------
# i18n / static
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# DRF / auth
# --------------------------------------------------------------------------

#: How many reverse proxies sit in front of Django and append to
#: X-Forwarded-For. The client address is taken that many hops from the RIGHT
#: of the header - the only part a client cannot forge. 0 means "trust no
#: header, use the socket address". Render and most PaaS load balancers: 1.
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)

# -- Cloudflare edge (docs/CLOUDFLARE.md) -------------------------------------
# off: no Cloudflare assumptions. report: requests carrying the origin secret
# are trusted as Cloudflare's (client IP from CF-Connecting-IP); others are
# logged. enforce: others are refused. Move off -> report -> enforce only after
# the DNS points at Cloudflare and the Transform Rule adds the header.
CLOUDFLARE_MODE = (env("CLOUDFLARE_MODE", "off") or "off").strip().lower()
# The value Cloudflare's Transform Rule sets on X-VerifyGH-Origin. A secret:
# Railway and Cloudflare only, never committed, never sent to the browser.
CLOUDFLARE_ORIGIN_SECRET = env("CLOUDFLARE_ORIGIN_SECRET", "") or ""

# -- Cloudflare Turnstile (apps/accounts/turnstile.py) -------------------------
# The secret half of the widget; the site key is the frontend's
# NEXT_PUBLIC_TURNSTILE_SITE_KEY. Set, sign-in and registration need a token
# Cloudflare confirms. Unset, there is no check (local development). A secret:
# Railway only, never committed, never sent to the browser.
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", "") or ""
# The hostnames a token may have been solved on. Empty: not checked.
TURNSTILE_ALLOWED_HOSTNAMES = env_list("TURNSTILE_ALLOWED_HOSTNAMES")

# -- Official brand logos (apps/catalog/brand_logos.py) -----------------------
# Brandfetch's client ID, from its developer portal. Unset: Admin > Logos says
# so and searches nothing. It appears in every logo URL, so it is not secret.
BRANDFETCH_CLIENT_ID = env("BRANDFETCH_CLIENT_ID", "") or ""

# -- Sign in with Google (apps/accounts/google.py) -----------------------------
# A "Web application" OAuth client from Google Cloud Console. Both set: the
# "Continue with Google" button appears. The redirect URI must match one
# registered on that client exactly. The client secret never leaves the server.
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", "") or ""
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", "") or ""
GOOGLE_OAUTH_REDIRECT_URI = (
    env("GOOGLE_OAUTH_REDIRECT_URI", "") or "http://localhost:8000/api/v1/auth/google/callback/"
)

REST_FRAMEWORK = {
    # DRF's default (None) uses the *entire* client-supplied X-Forwarded-For as
    # the throttle key, so rotating a fake header defeats every rate limit.
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    # One class, deliberately. CookieJWTAuthentication handles both the cookie
    # and the Authorization header, and enforces revocation on both. Listing
    # plain JWTAuthentication as a fallback would let a bearer token skip the
    # session-epoch and suspension checks entirely.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # JSON only unless DEBUG. DRF's browsable API renders HTML forms describing
    # every endpoint, its methods and its fields - a free map of the API for
    # anyone who sends `Accept: text/html`, and a rendering surface we do not
    # need in production.
    "DEFAULT_RENDERER_CLASSES": (
        [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
        if DEBUG
        else ["rest_framework.renderers.JSONRenderer"]
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "EXCEPTION_HANDLER": "apps.common.errors.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.common.throttling.ScopedBurstThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "240/min",
        "login": "8/min",
        # Per-IP ceiling across *all* accounts - stops credential stuffing,
        # which the per-(IP, email) bucket above does not see at all.
        "login_ip": "30/min",
        "referral_validate": "30/min",
        "register": "5/hour",
        "password_reset": "5/hour",
        "email_verify": "5/hour",
        # Typed codes and self-service address corrections, per user.
        "email_code": "20/hour",
        "email_change": "5/hour",
        # Keyed on IP *and* the submitted address, so one person cannot
        # use one address to mail-bomb another.
        "email_verify_resend": "5/hour",
        "deposit": "10/hour",
        "otp_submit": "20/hour",
        "order_create": "20/hour",
        "issue_report": "10/hour",
        "webhook": "600/min",
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("ACCESS_TOKEN_MINUTES", 20)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("REFRESH_TOKEN_DAYS", 14)),
    "ROTATE_REFRESH_TOKENS": True,
    # Every refresh mints a new token and blacklists the one presented. Replaying
    # an old refresh token therefore fails, which also surfaces token theft.
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": env("JWT_SIGNING_KEY") or SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

#: Claim carrying the user's session epoch. Blacklisting revokes one *refresh*
#: token; bumping this revokes every token a user holds, including access tokens
#: that are already issued and otherwise valid for their full lifetime. Used on
#: password change, password reset, suspension and "sign out everywhere".
TOKEN_VERSION_CLAIM = "ver"

# Cookie-based JWT transport. The access/refresh tokens live in httpOnly cookies
# so a XSS bug cannot read them; a readable CSRF cookie must be echoed back in a
# header on unsafe methods (double-submit), which a cross-site page cannot do.
AUTH_COOKIE_ACCESS = "vgh_access"
AUTH_COOKIE_REFRESH = "vgh_refresh"
AUTH_COOKIE_CSRF = "vgh_csrf"
AUTH_COOKIE_CSRF_HEADER = "HTTP_X_CSRF_TOKEN"
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE", not DEBUG)
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE", "Lax")
AUTH_COOKIE_DOMAIN = env("AUTH_COOKIE_DOMAIN") or None

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept", "authorization", "content-type", "origin", "user-agent",
    "x-csrf-token", "x-idempotency-key", "x-requested-with",
]
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")

# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 90
CELERY_TIMEZONE = TIME_ZONE

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
    if env("REDIS_URL")
    else {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "verifygh-local",
    }
}

# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

# Transactional email goes through Brevo's transactional email API, from a
# Django email backend (apps/notifications/brevo.py). HTTPS, not SMTP: Railway
# blocks the standard SMTP ports, and the API says *why* when Brevo refuses a
# message. Every email still goes through notify() -> EmailChannel ->
# EmailMultiAlternatives, so nothing above the backend knows the provider.
#
# The API key (xkeysib-...) only ever comes from the environment.
BREVO_API_KEY = env("BREVO_API_KEY", "")

_email_backend = env("EMAIL_BACKEND", "")

if BREVO_API_KEY and not _email_backend:
    # Setting one variable is enough to send real mail. An explicit
    # EMAIL_BACKEND still wins, so dev and the test suite can opt out.
    EMAIL_BACKEND = "apps.notifications.brevo.BrevoEmailBackend"
else:
    EMAIL_BACKEND = _email_backend or "django.core.mail.backends.console.EmailBackend"

# Only for an SMTP provider chosen explicitly with EMAIL_BACKEND.
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

# A mail server that accepts the connection and then stops talking would
# otherwise hold a web worker open indefinitely.
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 10)

#: Backends that accept a message and deliver it nowhere. Production refuses to
#: boot on one of these: an email written to stdout is indistinguishable, from
#: the application's point of view, from one that was delivered - which is
#: exactly how "verification emails never arrive" goes unnoticed.
NON_DELIVERING_EMAIL_BACKENDS = (
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
    "django.core.mail.backends.dummy.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",
)

# Who emails come from. BREVO_SENDER_EMAIL must be a sender verified in Brevo,
# on a domain authenticated there (docs/EMAIL.md). Without it, DEFAULT_FROM_EMAIL
# is used as before. Reserved TLDs (.example, .invalid, .test) are rejected
# outright by real mail providers, so the default has to be a plausible address.
BREVO_SENDER_EMAIL = env("BREVO_SENDER_EMAIL", "") or ""
BREVO_SENDER_NAME = (env("BREVO_SENDER_NAME", "") or "VerifyGH").replace('"', "")[:70]
DEFAULT_FROM_EMAIL = (
    f'"{BREVO_SENDER_NAME}" <{BREVO_SENDER_EMAIL}>' if BREVO_SENDER_EMAIL
    else env("DEFAULT_FROM_EMAIL", "") or "VerifyGH <no-reply@verifygh.com>"
)
SERVER_EMAIL = env("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# --------------------------------------------------------------------------
# VerifyGH domain configuration
# --------------------------------------------------------------------------

VERIFYGH = {
    "BRAND_NAME": "VerifyGH",
    #: Where customers write to; shown in every email's footer.
    "SUPPORT_EMAIL": env("SUPPORT_EMAIL", "support@getverifygh.com"),
    "CURRENCY": "GHS",
    "FRONTEND_URL": env("FRONTEND_URL", "http://localhost:3000"),
    # Provider selection — swapping a provider is a config change, not a rewrite.
    # Production: textverified (see docs/PROVIDERS.md). Selecting a provider is
    # not permission to sell through it - that is Provider.resale_authorized.
    "VERIFICATION_PROVIDER": env("VERIFICATION_PROVIDER", "mock"),
    "PAYMENT_PROVIDER": env("PAYMENT_PROVIDER", "mock"),
    # Providers whose webhook endpoint is live. Defaults to the active provider
    # only. Add the outgoing provider here during a switchover so in-flight
    # payments can still complete (see docs/PAYMENT_INTEGRATION.md).
    "WEBHOOK_PROVIDERS": env_list("WEBHOOK_PROVIDERS", ""),
    "EXCHANGE_RATE_PROVIDER": env("EXCHANGE_RATE_PROVIDER", "manual"),
    # Wallet / deposit limits (GHS)
    "MIN_DEPOSIT": env("MIN_DEPOSIT", "10.00"),
    "MAX_DEPOSIT": env("MAX_DEPOSIT", "2000.00"),
    "MAX_WALLET_BALANCE": env("MAX_WALLET_BALANCE", "10000.00"),
    # Anti-abuse controls
    "MAX_ACTIVE_ORDERS": env_int("MAX_ACTIVE_ORDERS", 5),
    # How many orders the whole platform may have in flight at once, across
    # every user. This exists to stay *below* the provider's own ceiling on
    # numbers held simultaneously. OnlineSim's standard limit was 40 (support,
    # 2026-09-27). TextVerified publishes no number: its API answers
    # TooManyUnfinishedVerifications past its limit, and its FAQ offers to raise
    # concurrency for power users on request - ask for the figure in writing.
    #
    # Deliberately lower than theirs. Our count and the provider's can drift:
    # closing an operation is not instant (their protective interval refuses a
    # close for 120s with no SMS), so a number we consider released may still be
    # held upstream. Without headroom we would discover their ceiling by hitting
    # it - mid-purchase, after the wallet was debited, with an opaque upstream
    # error. 32 of 40 leaves eight slots for that drift.
    #
    # Set to 0 to disable, which is right for the mock provider, where no
    # upstream ceiling exists.
    "MAX_PLATFORM_ACTIVE_ORDERS": env_int("MAX_PLATFORM_ACTIVE_ORDERS", 32),
    # Refuse Mobile Money top-ups while there is nothing to spend them on.
    #
    # Taking a deposit into an empty marketplace is taking real money for
    # something we cannot deliver. The money is not lost - it sits in the wallet
    # - but the user cannot buy with it and cannot withdraw it, which is
    # indistinguishable from having been robbed.
    #
    # Set to false only where an empty catalogue is expected and deposits are
    # being exercised deliberately, e.g. a staging stack on the mock provider.
    "REQUIRE_CATALOG_FOR_DEPOSIT": env_bool("REQUIRE_CATALOG_FOR_DEPOSIT", True),
    # Manual MoMo top-ups (apps/payments/manual.py), switched on in the admin.
    "MANUAL_DEPOSIT_NUMBER": env("MANUAL_DEPOSIT_NUMBER", ""),
    "MANUAL_DEPOSIT_NETWORK": env("MANUAL_DEPOSIT_NETWORK", "AirtelTigo Money"),
    "MANUAL_DEPOSIT_ACCOUNT_NAME": env("MANUAL_DEPOSIT_ACCOUNT_NAME", ""),
    "MANUAL_DEPOSIT_USSD": env("MANUAL_DEPOSIT_USSD", "*246#"),
    "MANUAL_DEPOSIT_MAX": env("MANUAL_DEPOSIT_MAX", "200.00"),
    "MANUAL_DEPOSIT_DAILY_LIMIT": env("MANUAL_DEPOSIT_DAILY_LIMIT", "400.00"),
    "MANUAL_DEPOSIT_MAX_OPEN": env_int("MANUAL_DEPOSIT_MAX_OPEN", 2),
    "MAX_ORDERS_PER_DAY": env_int("MAX_ORDERS_PER_DAY", 25),
    "MAX_DAILY_SPEND": env("MAX_DAILY_SPEND", "1500.00"),
    "MAX_FAILED_LOGINS": env_int("MAX_FAILED_LOGINS", 8),
    "LOGIN_LOCKOUT_MINUTES": env_int("LOGIN_LOCKOUT_MINUTES", 15),
    "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE": env_bool(
        "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE", True
    ),
    # Top-ups too (9 Oct 2026): an unverified wallet could take money it could
    # not spend, behind an address nobody could reach.
    "REQUIRE_EMAIL_VERIFICATION_FOR_DEPOSIT": env_bool(
        "REQUIRE_EMAIL_VERIFICATION_FOR_DEPOSIT", True),
    # How long a verification link stays usable. Long enough to survive a slow
    # inbox or a night's sleep, short enough that a link left sitting in an
    # abandoned mailbox is not a standing key to the account.
    "EMAIL_VERIFICATION_TTL_HOURS": env_int("EMAIL_VERIFICATION_TTL_HOURS", 24),
    "PASSWORD_RESET_TTL_HOURS": env_int("PASSWORD_RESET_TTL_HOURS", 2),
    # Provider contract: only show codes if the upstream agreement permits it.
    "DISPLAY_VERIFICATION_CODES": env_bool("DISPLAY_VERIFICATION_CODES", True),
    # Order lifecycle
    "ORDER_TTL_MINUTES": env_int("ORDER_TTL_MINUTES", 20),
    "ORDER_POLL_SECONDS": env_int("ORDER_POLL_SECONDS", 5),
    "PAYMENT_TTL_MINUTES": env_int("PAYMENT_TTL_MINUTES", 15),
    # How many provider services to price per catalogue sync. The service list
    # and the price are separate calls upstream, so this bounds the sync.
    # 0 means no ceiling. TextVerified also stops at a 60-second budget or its
    # first 429 and resumes where it left off on the next sync.
    "PROVIDER_CATALOG_LIMIT": env_int("PROVIDER_CATALOG_LIMIT", 60),
    # A price fetched this recently is not fetched again by the next sync: the
    # call goes to a service whose price is older. 0 reprices everything.
    "CATALOG_PRICE_FRESH_MINUTES": env_int("CATALOG_PRICE_FRESH_MINUTES", 150),
    # Which countries fill the bounded catalogue first. Without this the order
    # is whatever the provider happens to return, and the limit decides the
    # shop window by accident.
    "PROVIDER_PRIORITY_COUNTRIES": env_list("PROVIDER_PRIORITY_COUNTRIES", "US"),
    # -- marketplace ---------------------------------------------------------
    # The only countries a customer may browse or buy, as ISO alpha-2 codes.
    # Enforced on the server - the marketplace, quotes and order creation all
    # refuse anything else - and the catalogue sync only walks these, so
    # adding a country is a variable change plus a sync, not a code change.
    "MARKETPLACE_COUNTRIES": env_list("MARKETPLACE_COUNTRIES", "US"),
    # At or below this many numbers in stock, an offering shows as "Limited".
    "AVAILABILITY_LIMITED_THRESHOLD": env_int("AVAILABILITY_LIMITED_THRESHOLD", 10),
    # Above this, show "Available" rather than a count. OnlineSim reports 9999
    # for almost everything; printing "9,999 available" would present what is
    # very likely a ceiling as a stock level.
    "AVAILABILITY_EXACT_COUNT_MAX": env_int("AVAILABILITY_EXACT_COUNT_MAX", 999),
    # Ask the provider for live stock just before charging, instead of trusting
    # the last sync. One upstream call per purchase.
    "CHECK_LIVE_AVAILABILITY": env_bool("CHECK_LIVE_AVAILABILITY", True),
    "POPULAR_SERVICES_LIMIT": env_int("POPULAR_SERVICES_LIMIT", 10),
    # Sent as maxPrice when reserving: the most we accept paying above the
    # price we just quoted, if the provider moved it in between.
    "PROVIDER_PRICE_TOLERANCE": env("PROVIDER_PRICE_TOLERANCE", "1.05"),
    # Upstream call budget — we never hammer a provider API.
    "PROVIDER_RATE_LIMIT_PER_MINUTE": env_int("PROVIDER_RATE_LIMIT_PER_MINUTE", 120),
    # -- provider funding (apps/funding, docs/PROVIDER-FUNDING.md). OnlineSim is
    # prepaid: numbers are bought from our own balance there, which staff top
    # up by hand. These keep a purchase from charging a customer when that
    # balance cannot cover it, and tell staff before it runs out.
    #
    # Refuse a purchase before charging when the provider balance is known to
    # be too low. Off = the old behaviour: charge, fail at the provider, refund.
    "PROVIDER_FUNDING_GUARD": env_bool("PROVIDER_FUNDING_GUARD", True),
    # Reserve levels given to a provider account when it is first created, in
    # the provider's currency. Staff change them in Admin > Provider funding.
    "PROVIDER_RESERVE_CRITICAL": env("PROVIDER_RESERVE_CRITICAL", "2"),
    "PROVIDER_RESERVE_MINIMUM": env("PROVIDER_RESERVE_MINIMUM", "5"),
    "PROVIDER_RESERVE_TARGET": env("PROVIDER_RESERVE_TARGET", "20"),
    # One alert of a kind per provider per this many minutes.
    "PROVIDER_ALERT_COOLDOWN_MINUTES": env_int("PROVIDER_ALERT_COOLDOWN_MINUTES", 60),
    # Balance reads that must fail in a row before staff are told.
    "PROVIDER_SYNC_FAILURE_ALERT_AFTER": env_int("PROVIDER_SYNC_FAILURE_ALERT_AFTER", 3),
    # Failed orders at one provider within the window that count as a spike.
    "PROVIDER_FAILURE_SPIKE_THRESHOLD": env_int("PROVIDER_FAILURE_SPIKE_THRESHOLD", 5),
    "PROVIDER_FAILURE_SPIKE_WINDOW_MINUTES": env_int("PROVIDER_FAILURE_SPIKE_WINDOW_MINUTES", 30),
    # OnlineSim deletes an account, balance included, 30 days after its last
    # completed purchase (Terms 11.4/11.5). Warn this many days in.
    "PROVIDER_INACTIVITY_DELETION_DAYS": env_int("PROVIDER_INACTIVITY_DELETION_DAYS", 30),
    "PROVIDER_INACTIVITY_WARNING_DAYS": env_int("PROVIDER_INACTIVITY_WARNING_DAYS", 20),
    # A recorded top-up the balance has not reflected after this long is flagged.
    "PROVIDER_TOP_UP_CONFIRM_HOURS": env_int("PROVIDER_TOP_UP_CONFIRM_HOURS", 24),
    "CURRENT_TERMS_VERSION": env("CURRENT_TERMS_VERSION", "2026-01-01"),
    # -- number quality (apps/numbers). The replacement/refund *policy* lives
    # here rather than in code, so the business can change it with a variable.
    #
    # How long after the code arrived a customer may report a problem.
    "NUMBER_ISSUE_REPORT_WINDOW_HOURS": env_int("NUMBER_ISSUE_REPORT_WINDOW_HOURS", 72),
    # What staff may do about an upheld report: any of REFUND, REPLACE. Neither
    # happens on its own - a delivered code is a delivered service under the
    # refund policy, so every remedy is a recorded staff decision.
    "NUMBER_ISSUE_REMEDIES": env_list("NUMBER_ISSUE_REMEDIES", "REFUND,REPLACE"),
    # Reports by one customer in 30 days before their cases are flagged for a
    # closer look. Flagged, never refused.
    "NUMBER_ISSUE_REVIEW_THRESHOLD": env_int("NUMBER_ISSUE_REVIEW_THRESHOLD", 3),
    # When a report goes to a provider that refunds reported verifications
    # (TextVerified), how long its decision usually takes. TextVerified
    # publishes no figure, so this is a starting estimate to tune: it is only
    # the "decision expected by" the customer sees, and passing it never closes
    # the claim.
    "NUMBER_ISSUE_PROVIDER_DECISION_HOURS": env_int("NUMBER_ISSUE_PROVIDER_DECISION_HOURS", 48),
    # How soon after the code arrives such a provider still takes a report.
    # TextVerified publishes no figure; it declined a claim filed 6 minutes
    # after the code arrived, so 5 is the working value until they confirm it.
    # Customers see this as a countdown, and the report button closes with it.
    "NUMBER_ISSUE_PROVIDER_REPORT_WINDOW_MINUTES": env_int(
        "NUMBER_ISSUE_PROVIDER_REPORT_WINDOW_MINUTES", 5),
    # Screenshots a customer attaches to a report.
    "NUMBER_ISSUE_EVIDENCE_MAX_FILES": env_int("NUMBER_ISSUE_EVIDENCE_MAX_FILES", 3),
    "NUMBER_ISSUE_EVIDENCE_MAX_BYTES": env_int("NUMBER_ISSUE_EVIDENCE_MAX_BYTES", 5 * 1024 * 1024),
    # How many times one purchase may turn away a flagged number and draw
    # again before giving up and refunding.
    "NUMBER_QUALITY_MAX_REDRAWS": env_int("NUMBER_QUALITY_MAX_REDRAWS", 2),
    # -- referral programme. These seed the ReferralProgram row the first time
    # it is read; after that the database is the source of truth, so an admin
    # can change the bonus without a deploy.
    "REFERRAL_PROGRAM_ENABLED": env_bool("REFERRAL_PROGRAM_ENABLED", True),
    "REFERRAL_SIGNUP_BONUS": env("REFERRAL_SIGNUP_BONUS_GHS", "5.00"),
    "REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS": env_int(
        "REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS", 20
    ),
    "REFERRAL_REQUIRE_PHONE_VERIFICATION": env_bool(
        "REFERRAL_REQUIRE_PHONE_VERIFICATION", False
    ),
    # Codes and SMS text are erased from finished orders after this many days.
    "VERIFICATION_DATA_RETENTION_DAYS": env_int("VERIFICATION_DATA_RETENTION_DAYS", 30),
}

PROVIDER_CREDENTIALS = {
    # Legacy: OnlineSim is no longer the active provider (2026-09-29). Kept so
    # orders made through it can still be read back; production does not need
    # these once no OnlineSim order is in flight.
    "onlinesim": {
        "api_key": env("ONLINESIM_API_KEY", ""),
        # Their documented host. Overridable only so a test can point elsewhere.
        "base_url": env("ONLINESIM_BASE_URL", ""),
        # Tariffs are returned in the profile's own currency, USD by default.
        # Set this to whatever the OnlineSim profile is configured for, or the
        # exchange rate will be applied to the wrong unit.
        "currency": env("ONLINESIM_CURRENCY", "USD"),
    },
    # The primary provider. The documented auth call takes the account email
    # (api_username) and the API key from the TextVerified dashboard; both are
    # secrets as far as this codebase is concerned: never logged, never sent to
    # the browser. base_url stays empty for the documented host.
    "textverified": {
        "api_key": env("TEXTVERIFIED_API_KEY", ""),
        "api_username": env("TEXTVERIFIED_API_USERNAME", ""),
        "base_url": env("TEXTVERIFIED_BASE_URL", ""),
        # Optional. The `whsec_...` secret from TextVerified's API Webhook
        # Settings. Set it and signed v2.sms.received callbacks prompt an
        # immediate read of the order; without it we poll only.
        "webhook_secret": env("TEXTVERIFIED_WEBHOOK_SECRET", ""),
    },
}

PAYMENT_CREDENTIALS = {
    "paystack": {
        "secret_key": env("PAYSTACK_SECRET_KEY", ""),
        "public_key": env("PAYSTACK_PUBLIC_KEY", ""),
        "base_url": env("PAYSTACK_BASE_URL", "https://api.paystack.co"),
    },
    "hubtel": {
        "client_id": env("HUBTEL_CLIENT_ID", ""),
        "client_secret": env("HUBTEL_CLIENT_SECRET", ""),
        # Hubtel identifies the merchant account the money lands in; the
        # documentation will say whether it belongs in the path or the body.
        "merchant_account": env("HUBTEL_MERCHANT_ACCOUNT", ""),
        "base_url": env("HUBTEL_BASE_URL", ""),
    },
    "moolre": {
        # The username shown in the Moolre dashboard (X-API-USER) and the
        # public key of the wallet's API service (X-API-PUBKEY). Payments and
        # status checks need only these; the private key is never used here.
        "username": env("MOOLRE_USERNAME", ""),
        "public_key": env("MOOLRE_PUBLIC_KEY", ""),
        # The wallet the money lands in, and its callback secret.
        "account_number": env("MOOLRE_ACCOUNT_NUMBER", ""),
        "callback_secret": env("MOOLRE_CALLBACK_SECRET", ""),
        "base_url": env("MOOLRE_BASE_URL", "https://api.moolre.com"),
    },
    "sendi": {
        # The secret key (sk_live_...) from Merchant API > API keys, and the
        # webhook signing secret from Merchant API > Webhook.
        "secret_key": env("SENDI_SECRET_KEY", ""),
        "webhook_secret": env("SENDI_WEBHOOK_SECRET", ""),
        "base_url": env("SENDI_BASE_URL", "https://mesendi.com/backend"),
    },
    "mock": {"secret_key": env("MOCK_PAYMENT_SECRET", "mock-webhook-secret")},
}

EXCHANGE_RATE_API_KEY = env("EXCHANGE_RATE_API_KEY", "")

# --------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --------------------------------------------------------------------------
# Logging — structured, and redacted so no secret or verification code lands in logs.
# --------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {"()": "apps.common.logging.RedactingFilter"},
        "request_context": {"()": "apps.common.logging.RequestContextFilter"},
    },
    "formatters": {
        "json": {"()": "apps.common.logging.JsonFormatter"},
        "console": {
            "format": "{levelname} {asctime} {name} {request_id} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact", "request_context"],
            "formatter": env("LOG_FORMAT", "console"),
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "verifygh": {
            "level": env("LOG_LEVEL", "INFO"),
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
