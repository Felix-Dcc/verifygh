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
    "apps.notifications",
    "apps.adminapi",
    "apps.referrals",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestContextMiddleware",
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
        "email_verify": "10/hour",
        "deposit": "10/hour",
        "order_create": "20/hour",
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

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "VerifyGH <no-reply@verifygh.example>")

# --------------------------------------------------------------------------
# VerifyGH domain configuration
# --------------------------------------------------------------------------

VERIFYGH = {
    "BRAND_NAME": "VerifyGH",
    "CURRENCY": "GHS",
    "FRONTEND_URL": env("FRONTEND_URL", "http://localhost:3000"),
    # Provider selection — swapping a provider is a config change, not a rewrite.
    "VERIFICATION_PROVIDER": env("VERIFICATION_PROVIDER", "mock"),
    "PAYMENT_PROVIDER": env("PAYMENT_PROVIDER", "mock"),
    # Providers whose webhook endpoint is live. Defaults to the active provider
    # only. Add the outgoing provider here during a switchover so in-flight
    # payments can still complete (see docs/PAYMENT_INTEGRATION.md).
    "WEBHOOK_PROVIDERS": env_list("WEBHOOK_PROVIDERS", ""),
    "EXCHANGE_RATE_PROVIDER": env("EXCHANGE_RATE_PROVIDER", "manual"),
    # Wallet / deposit limits (GHS)
    "MIN_DEPOSIT": env("MIN_DEPOSIT", "5.00"),
    "MAX_DEPOSIT": env("MAX_DEPOSIT", "2000.00"),
    "MAX_WALLET_BALANCE": env("MAX_WALLET_BALANCE", "10000.00"),
    # Anti-abuse controls
    "MAX_ACTIVE_ORDERS": env_int("MAX_ACTIVE_ORDERS", 5),
    "MAX_ORDERS_PER_DAY": env_int("MAX_ORDERS_PER_DAY", 25),
    "MAX_DAILY_SPEND": env("MAX_DAILY_SPEND", "1500.00"),
    "MAX_FAILED_LOGINS": env_int("MAX_FAILED_LOGINS", 8),
    "LOGIN_LOCKOUT_MINUTES": env_int("LOGIN_LOCKOUT_MINUTES", 15),
    "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE": env_bool(
        "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE", True
    ),
    # Provider contract: only show codes if the upstream agreement permits it.
    "DISPLAY_VERIFICATION_CODES": env_bool("DISPLAY_VERIFICATION_CODES", True),
    # Order lifecycle
    "ORDER_TTL_MINUTES": env_int("ORDER_TTL_MINUTES", 20),
    "ORDER_POLL_SECONDS": env_int("ORDER_POLL_SECONDS", 5),
    "PAYMENT_TTL_MINUTES": env_int("PAYMENT_TTL_MINUTES", 15),
    # Upstream call budget — we never hammer a provider API.
    "PROVIDER_RATE_LIMIT_PER_MINUTE": env_int("PROVIDER_RATE_LIMIT_PER_MINUTE", 120),
    "CURRENT_TERMS_VERSION": env("CURRENT_TERMS_VERSION", "2026-01-01"),
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
    "textverified": {
        "api_key": env("TEXTVERIFIED_API_KEY", ""),
        "api_username": env("TEXTVERIFIED_API_USERNAME", ""),
        "base_url": env("TEXTVERIFIED_BASE_URL", ""),
    },
}

PAYMENT_CREDENTIALS = {
    "paystack": {
        "secret_key": env("PAYSTACK_SECRET_KEY", ""),
        "public_key": env("PAYSTACK_PUBLIC_KEY", ""),
        "base_url": env("PAYSTACK_BASE_URL", "https://api.paystack.co"),
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
