"""Production settings.

This module refuses to import if a required secret is missing. Failing at boot
is much cheaper than discovering at 2am that the app ran with a dev secret key.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import VERIFYGH, env, env_bool, env_int, env_list

DEBUG = False

_REQUIRED = [
    "SECRET_KEY",
    # Separate from SECRET_KEY, so rotating one (e.g. after a leak) does not
    # silently invalidate - or fail to invalidate - the other.
    "JWT_SIGNING_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "ALLOWED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "FRONTEND_URL",
]

_missing = [name for name in _REQUIRED if not env(name)]
if _missing:
    raise ImproperlyConfigured(
        "Missing required production environment variables: " + ", ".join(_missing)
    )

_problems: list[str] = []

_secret_key = env("SECRET_KEY", "")
_jwt_key = env("JWT_SIGNING_KEY", "")
if _secret_key.startswith(("dev-", "django-insecure")):
    _problems.append("SECRET_KEY still holds a development value.")
if len(_secret_key) < 50:
    _problems.append("SECRET_KEY must be at least 50 characters.")
if len(_jwt_key) < 50:
    _problems.append("JWT_SIGNING_KEY must be at least 50 characters.")
if _jwt_key == _secret_key:
    _problems.append("JWT_SIGNING_KEY must differ from SECRET_KEY.")

# Rate limits key on the client IP, which comes from X-Forwarded-For counted
# from the right. Too low and every user shares the load balancer's IP (one
# user's failed logins lock out everyone); too high and the header is
# spoofable. There is no safe default, so it must be stated.
if env("TRUSTED_PROXY_COUNT") in (None, ""):
    _problems.append("TRUSTED_PROXY_COUNT must be set explicitly (proxy hops in front of the API).")

# Credentials and balances cross this connection.
if env("DB_SSLMODE", "prefer") not in ("require", "verify-ca", "verify-full") and not env_bool(
    "ALLOW_UNENCRYPTED_DATABASE", False
):
    _problems.append("DB_SSLMODE must be require, verify-ca or verify-full.")

_pool_mode = env("DB_POOL_MODE", "session")
if _pool_mode not in ("session", "transaction"):
    _problems.append("DB_POOL_MODE must be 'session' or 'transaction'.")
# 6543 is the conventional transaction-mode pooler port (PgBouncer and the
# managed poolers that follow it). Without the matching settings the app boots
# and works, then the nightly wallet reconciliation fails - the one job that
# would notice a ledger problem.
if str(DATABASES["default"].get("PORT")) == "6543" and _pool_mode != "transaction":  # noqa: F405
    _problems.append(
        "DATABASE_URL uses port 6543 (a transaction pooler): set DB_POOL_MODE=transaction."
    )

for _name in ("CORS_ALLOWED_ORIGINS", "FRONTEND_URL"):
    for _origin in env_list(_name):
        if not _origin.startswith("https://"):
            _problems.append(f"{_name} must use https:// ({_origin!r}).")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")

# Terminated at the load balancer; trust its forwarded scheme header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
AUTH_COOKIE_SECURE = True
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE", "None")

CELERY_TASK_ALWAYS_EAGER = False

# A live payment provider without a webhook secret would accept forged
# callbacks. Never let that combination boot.
_payment_provider = VERIFYGH["PAYMENT_PROVIDER"]
if _payment_provider == "mock":
    raise ImproperlyConfigured("PAYMENT_PROVIDER=mock is not allowed in production.")
if _payment_provider == "paystack":
    _paystack_key = env("PAYSTACK_SECRET_KEY", "")
    if not _paystack_key:
        _problems.append("PAYSTACK_SECRET_KEY is required when PAYMENT_PROVIDER=paystack.")
    elif _paystack_key.startswith("pk_"):
        _problems.append("PAYSTACK_SECRET_KEY holds a public key (pk_...), not a secret key.")
    elif not _paystack_key.startswith("sk_live_") and not env_bool(
        "ALLOW_PAYSTACK_TEST_KEYS", False
    ):
        # A test key in production takes no real money but credits real
        # wallets - every "payment" would be free.
        _problems.append("PAYSTACK_SECRET_KEY is not a live key (sk_live_...). "
                         "Set ALLOW_PAYSTACK_TEST_KEYS=true only on a non-public staging stack.")

# The mock verification provider hands out simulated numbers. In production
# that means taking real cedis for nothing. Until an authorised provider is
# configured, run with VERIFICATION_PROVIDER=textverified: its endpoints are
# deliberately blank, so the catalogue stays empty and nothing can be bought.
if VERIFYGH["VERIFICATION_PROVIDER"] == "mock" and not env_bool(
    "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION", False
):
    raise ImproperlyConfigured(
        "VERIFICATION_PROVIDER=mock would sell simulated numbers for real money. "
        "Use textverified (inert until configured), or set "
        "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION=true for a non-public staging stack."
    )

# The mock adapter signs with a secret that is published in .env.example. Its
# webhook endpoint must never be reachable in production.
if "mock" in VERIFYGH.get("WEBHOOK_PROVIDERS", []):
    raise ImproperlyConfigured("WEBHOOK_PROVIDERS must not include 'mock' in production.")

if _problems:
    raise ImproperlyConfigured("Unsafe production configuration:\n  - " + "\n  - ".join(_problems))

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405

# base.py builds REST_FRAMEWORK from the *environment's* DEBUG, before this
# module sets DEBUG = False. Pin JSON-only here so the browsable API can never
# be switched back on by a stray DEBUG=true in the deploy environment.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
