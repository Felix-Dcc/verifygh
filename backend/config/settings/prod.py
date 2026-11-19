"""Production settings.

This module refuses to import if a required secret is missing. Failing at boot
is much cheaper than discovering at 2am that the app ran with a dev secret key.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import (
    DEFAULT_FROM_EMAIL,
    EMAIL_BACKEND,
    EMAIL_HOST,
    EMAIL_HOST_PASSWORD,
    NON_DELIVERING_EMAIL_BACKENDS,
    VERIFYGH,
    env,
    env_bool,
    env_int,
    env_list,
)

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
# The platform healthcheck reaches the container over plain HTTP on the private
# network and does not set X-Forwarded-Proto, so SECURE_SSL_REDIRECT answers it
# with a 301 and the deployment is marked unhealthy - the old container then
# keeps serving, which is a silent and very confusing failure. Exempt the health
# endpoint only; every other path still redirects to HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^health/?$"]
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
AUTH_COOKIE_SECURE = True
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE", "None")

CELERY_TASK_ALWAYS_EAGER = False

# ---------------------------------------------------------------------------
# Transactional email
# ---------------------------------------------------------------------------
# Email verification is a security control: it is what stops one person opening
# accounts on other people's addresses, and it gates every purchase. A
# non-delivering backend does not disable that control, it makes it
# unsatisfiable - nobody can ever verify - while the application reports every
# send as successful. That is worse than an outage because nothing looks wrong,
# so it must be impossible to deploy.
if EMAIL_BACKEND in NON_DELIVERING_EMAIL_BACKENDS:
    _problems.append(
        f"EMAIL_BACKEND={EMAIL_BACKEND} delivers nothing: verification emails would be "
        "written to the container log instead of sent, and no account could ever be "
        "verified. Set BREVO_API_KEY (see docs/EMAIL.md)."
        + (" RESEND_API_KEY is no longer used." if env("RESEND_API_KEY", "") else "")
    )

if BREVO_API_KEY and not BREVO_API_KEY.startswith("xkeysib-"):  # noqa: F405
    # Brevo's API keys are prefixed xkeysib-. Its SMTP key (xsmtpsib-) looks
    # similar and does not work with the API; anything else is a placeholder.
    _problems.append(
        "BREVO_API_KEY does not look like a Brevo API key (expected xkeysib-...). The SMTP "
        "key (xsmtpsib-...) does not work with the API - create an API key in Brevo."
    )
if EMAIL_BACKEND.endswith("BrevoEmailBackend") and not BREVO_SENDER_EMAIL:  # noqa: F405
    _problems.append(
        "BREVO_SENDER_EMAIL is required: a sender verified in Brevo, on a domain "
        "authenticated there (docs/EMAIL.md)."
    )

if EMAIL_BACKEND.endswith("smtp.EmailBackend"):
    if not EMAIL_HOST:
        _problems.append("EMAIL_HOST is required when using the SMTP email backend.")
    if not EMAIL_HOST_PASSWORD:
        _problems.append(
            "No SMTP password is set: set EMAIL_HOST_PASSWORD, or use Brevo's API with "
            "BREVO_API_KEY."
        )

# The From address has to be one a real mail server will accept and a real
# domain the recipient can see is ours. The reserved TLDs below are guaranteed
# never to resolve, and providers reject them outright.
_sender = str(DEFAULT_FROM_EMAIL or "")
if "@" not in _sender:
    _problems.append("DEFAULT_FROM_EMAIL must be a full email address.")
elif _sender.rsplit("@", 1)[-1].rstrip(">").strip().lower().endswith(
    (".example", ".invalid", ".test", ".localhost", "example.com")
):
    _problems.append(
        f"DEFAULT_FROM_EMAIL uses a reserved domain that cannot send or receive mail "
        f"({_sender!r}). Use an address on a domain authenticated in Brevo."
    )

# Turning the purchase gate off in production would let an unverified account
# spend money, which is the specific thing email verification exists to stop.
if not VERIFYGH["REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE"]:
    _problems.append(
        "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE=false would let unverified accounts buy. "
        "It must be true in production."
    )

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

if _payment_provider == "moolre":
    for _name in ("MOOLRE_USERNAME", "MOOLRE_PUBLIC_KEY", "MOOLRE_ACCOUNT_NUMBER",
                  "MOOLRE_CALLBACK_SECRET"):
        if not env(_name, ""):
            _problems.append(f"{_name} is required when PAYMENT_PROVIDER=moolre.")
    # Sandbox payments succeed without any money moving: in production every
    # "deposit" would be free credit.
    if env("MOOLRE_BASE_URL", "https://api.moolre.com").rstrip("/") != "https://api.moolre.com" \
            and not env_bool("ALLOW_MOOLRE_SANDBOX", False):
        _problems.append("MOOLRE_BASE_URL is not the live API (https://api.moolre.com). "
                         "Set ALLOW_MOOLRE_SANDBOX=true only on a non-public staging stack.")

if _payment_provider == "sendi":
    for _name in ("SENDI_SECRET_KEY", "SENDI_WEBHOOK_SECRET"):
        if not env(_name, ""):
            _problems.append(f"{_name} is required when PAYMENT_PROVIDER=sendi.")
    _sendi_key = env("SENDI_SECRET_KEY", "")
    if _sendi_key.startswith("pk_"):
        _problems.append("SENDI_SECRET_KEY holds a public key (pk_...), not a secret key.")
    elif _sendi_key and not _sendi_key.startswith("sk_live_") and not env_bool(
        "ALLOW_SENDI_TEST_KEYS", False
    ):
        # Test charges complete on SENDI's page without money moving: every
        # "deposit" would be free credit.
        _problems.append("SENDI_SECRET_KEY is not a live key (sk_live_...). "
                         "Set ALLOW_SENDI_TEST_KEYS=true only on a non-public staging stack.")
    _sendi_url = env("SENDI_BASE_URL", "https://mesendi.com/backend").rstrip("/")
    if _sendi_url != "https://mesendi.com/backend" and not env_bool("ALLOW_SENDI_TEST_KEYS", False):
        _problems.append("SENDI_BASE_URL is not the live API (https://mesendi.com/backend).")

if _payment_provider == "mojopay":
    for _name in ("MOJOPAY_CLIENT_ID", "MOJOPAY_CLIENT_SECRET", "MOJOPAY_WEBHOOK_SECRET"):
        if not env(_name, ""):
            _problems.append(f"{_name} is required when PAYMENT_PROVIDER=mojopay.")
    if env("MOJOPAY_BASE_URL", "https://omni.mojo-pay.com").rstrip("/") \
            != "https://omni.mojo-pay.com":
        _problems.append("MOJOPAY_BASE_URL is not MojoPay's API (https://omni.mojo-pay.com).")

# An adapter whose endpoints are still blank cannot take a single cedi. Booting
# with one selected would leave every deposit failing in production while the
# app looked healthy, so refuse it here instead. This reads a plain data module:
# importing the adapters themselves from settings would be circular.
from apps.payments.implemented import IMPLEMENTED_PAYMENT_PROVIDERS  # noqa: E402

if _payment_provider not in IMPLEMENTED_PAYMENT_PROVIDERS:
    _problems.append(
        f"PAYMENT_PROVIDER={_payment_provider} is not implemented: its endpoints are still "
        "blank pending the provider's official API documentation. "
        f"Implemented: {', '.join(sorted(IMPLEMENTED_PAYMENT_PROVIDERS))}."
    )

# The mock verification provider hands out simulated numbers. In production
# that means taking real cedis for nothing.
if VERIFYGH["VERIFICATION_PROVIDER"] == "mock" and not env_bool(
    "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION", False
):
    raise ImproperlyConfigured(
        "VERIFICATION_PROVIDER=mock would sell simulated numbers for real money. "
        "Use textverified with its credentials, or set "
        "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION=true for a non-public staging stack."
    )

# The Cloudflare origin lock: a mode we do not know, or a lock without a
# strong secret, would look protected while protecting nothing.
if CLOUDFLARE_MODE not in {"off", "report", "enforce"}:  # noqa: F405
    _problems.append(f"CLOUDFLARE_MODE={CLOUDFLARE_MODE} must be off, report or enforce.")  # noqa: F405
elif CLOUDFLARE_MODE != "off" and len(CLOUDFLARE_ORIGIN_SECRET) < 32:  # noqa: F405
    _problems.append(
        "CLOUDFLARE_MODE is on but CLOUDFLARE_ORIGIN_SECRET is missing or shorter than 32 "
        "characters. Generate a long random value and set it in both Railway and the "
        "Cloudflare Transform Rule."
    )

# Sign in with Google: half a client cannot sign anyone in, and a plain-HTTP
# callback would carry the authorisation code in the clear.
if bool(GOOGLE_OAUTH_CLIENT_ID) != bool(GOOGLE_OAUTH_CLIENT_SECRET):  # noqa: F405
    _problems.append(
        "Sign in with Google needs both GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
        "(or neither)."
    )
elif GOOGLE_OAUTH_CLIENT_ID and not GOOGLE_OAUTH_REDIRECT_URI.startswith("https://"):  # noqa: F405
    _problems.append("GOOGLE_OAUTH_REDIRECT_URI must be an https:// address in production.")

# A real provider without its credentials fails here, at boot, rather than at
# the first customer's purchase - and never falls back to anything else.
_VERIFICATION_CREDENTIALS = {
    "textverified": {"api_username": "TEXTVERIFIED_API_USERNAME",
                     "api_key": "TEXTVERIFIED_API_KEY"},
    "onlinesim": {"api_key": "ONLINESIM_API_KEY"},
}
_verification_provider = VERIFYGH["VERIFICATION_PROVIDER"]
if _verification_provider != "mock":
    if _verification_provider not in _VERIFICATION_CREDENTIALS:
        _problems.append(
            f"VERIFICATION_PROVIDER={_verification_provider} is not a provider this "
            f"codebase has an adapter for: {', '.join(sorted(_VERIFICATION_CREDENTIALS))}."
        )
    else:
        _supplied = PROVIDER_CREDENTIALS.get(_verification_provider, {})  # noqa: F405
        _missing = [
            variable
            for field, variable in _VERIFICATION_CREDENTIALS[_verification_provider].items()
            if not str(_supplied.get(field) or "").strip()
        ]
        if _missing:
            _problems.append(
                f"VERIFICATION_PROVIDER={_verification_provider} needs {', '.join(_missing)}. "
                "Without them nothing can be sold, and there is no fallback provider."
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
