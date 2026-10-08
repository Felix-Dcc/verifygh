"""Production settings refuse every unsafe configuration we know of.

Each case boots `config.settings.prod` in a fresh interpreter - settings are
module-level code, so importing them in-process would leak between cases - from
a baseline that is known to boot, changing exactly one thing.

All values here are placeholders. `sk_live_` followed by zeros is not a Paystack
key; it only has the shape the guard checks for.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

SAFE = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "SECRET_KEY": "s" * 64,
    "JWT_SIGNING_KEY": "j" * 64,
    "DATABASE_URL": "postgres://app:placeholder@db.internal:5432/verifygh",
    "DB_SSLMODE": "require",
    "REDIS_URL": "redis://cache.internal:6379/0",
    "ALLOWED_HOSTS": "api.verifygh.example",
    "CORS_ALLOWED_ORIGINS": "https://verifygh.example",
    "FRONTEND_URL": "https://verifygh.example",
    "TRUSTED_PROXY_COUNT": "1",
    "PAYMENT_PROVIDER": "paystack",
    "PAYSTACK_SECRET_KEY": "sk_live_" + "0" * 40,
    "VERIFICATION_PROVIDER": "textverified",
    # Placeholders of the right presence, not real credentials: boot checks
    # they are set, it never calls the provider.
    "TEXTVERIFIED_API_USERNAME": "ops@verifygh.example",
    "TEXTVERIFIED_API_KEY": "placeholder-textverified-key",
    "ONLINESIM_API_KEY": "",
    "WEBHOOK_PROVIDERS": "",
    "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION": "",
    "ALLOW_PAYSTACK_TEST_KEYS": "",
    "ALLOW_UNENCRYPTED_DATABASE": "",
    # Not a real key: Brevo's `xkeysib-` prefix and placeholder characters,
    # which is only the shape the guard checks for.
    "BREVO_API_KEY": "xkeysib-" + "0" * 64,
    "BREVO_SENDER_EMAIL": "support@verifygh.com",
    "BREVO_SENDER_NAME": "VerifyGH",
    "DEFAULT_FROM_EMAIL": "",
    "EMAIL_BACKEND": "",
}

#: Variables that must not leak in from the developer's shell.
SCRUB = set(SAFE) | {"DEBUG", "MOCK_PAYMENT_SECRET", "REQUIRE_POSTGRES", "DB_POOL_MODE",
                    "TEXTVERIFIED_BASE_URL", "TEXTVERIFIED_WEBHOOK_SECRET", "ONLINESIM_BASE_URL",
                    "CLOUDFLARE_MODE", "CLOUDFLARE_ORIGIN_SECRET",
                    "TURNSTILE_SECRET_KEY", "TURNSTILE_ALLOWED_HOSTNAMES",
                    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
                    "GOOGLE_OAUTH_REDIRECT_URI",
                    "EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
                    "RESEND_API_KEY", "SUPPORT_EMAIL",
                    "REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE",
                    "DB_CONN_MAX_AGE", "DB_SSLROOTCERT", "HUBTEL_CLIENT_ID",
                    "HUBTEL_CLIENT_SECRET", "HUBTEL_MERCHANT_ACCOUNT", "HUBTEL_BASE_URL",
                    "MOOLRE_USERNAME", "MOOLRE_PUBLIC_KEY", "MOOLRE_ACCOUNT_NUMBER",
                    "MOOLRE_CALLBACK_SECRET", "MOOLRE_BASE_URL", "ALLOW_MOOLRE_SANDBOX"}


def boot(**changes) -> subprocess.CompletedProcess:
    child_env = {key: value for key, value in os.environ.items() if key not in SCRUB}
    child_env.update(SAFE)
    for key, value in changes.items():
        if value is None:
            child_env.pop(key, None)
        else:
            child_env[key] = value
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup(); "
         "from django.conf import settings; print('BOOTED', settings.DEBUG)"],
        cwd=BACKEND, env=child_env, capture_output=True, text=True, timeout=120,
    )


def test_the_safe_baseline_boots():
    result = boot()
    assert result.returncode == 0, result.stderr[-2000:]
    assert "BOOTED False" in result.stdout


UNSAFE = [
    ("missing secret key", {"SECRET_KEY": None}, "SECRET_KEY"),
    ("missing jwt key", {"JWT_SIGNING_KEY": None}, "JWT_SIGNING_KEY"),
    ("missing redis", {"REDIS_URL": None}, "REDIS_URL"),
    ("dev secret key", {"SECRET_KEY": "dev-" + "x" * 60}, "development value"),
    ("short secret key", {"SECRET_KEY": "short-but-not-dev"}, "at least 50"),
    ("short jwt key", {"JWT_SIGNING_KEY": "k" * 20}, "JWT_SIGNING_KEY must be at least"),
    ("jwt key reused", {"JWT_SIGNING_KEY": "s" * 64}, "must differ"),
    ("mock payments", {"PAYMENT_PROVIDER": "mock"}, "PAYMENT_PROVIDER=mock"),
    # An adapter whose endpoints are still blank cannot take a cedi. Booting
    # with it selected would look healthy while every deposit failed.
    ("unimplemented provider", {"PAYMENT_PROVIDER": "hubtel", "PAYSTACK_SECRET_KEY": None},
     "is not implemented"),
    ("unknown provider", {"PAYMENT_PROVIDER": "wakanda-pay", "PAYSTACK_SECRET_KEY": None},
     "is not implemented"),
    ("paystack without key", {"PAYSTACK_SECRET_KEY": None}, "PAYSTACK_SECRET_KEY is required"),
    ("paystack test key", {"PAYSTACK_SECRET_KEY": "sk_test_" + "0" * 40}, "not a live key"),
    ("paystack public key", {"PAYSTACK_SECRET_KEY": "pk_live_" + "0" * 40}, "public key"),
    ("moolre without credentials", {"PAYMENT_PROVIDER": "moolre", "PAYSTACK_SECRET_KEY": None},
     "MOOLRE_USERNAME is required"),
    # Sandbox payments succeed without money moving: every deposit free credit.
    ("moolre sandbox", {"PAYMENT_PROVIDER": "moolre", "PAYSTACK_SECRET_KEY": None,
                        "MOOLRE_USERNAME": "verifygh", "MOOLRE_PUBLIC_KEY": "p" * 32,
                        "MOOLRE_ACCOUNT_NUMBER": "10000000001", "MOOLRE_CALLBACK_SECRET": "s" * 36,
                        "MOOLRE_BASE_URL": "https://sandbox.moolre.com"},
     "not the live API"),
    ("mock webhook route", {"WEBHOOK_PROVIDERS": "mock"}, "must not include 'mock'"),
    ("mock verification", {"VERIFICATION_PROVIDER": "mock"}, "simulated numbers"),
    # The primary provider without its credentials fails at boot - never at the
    # first purchase, and never by falling back to something else.
    ("textverified without api key", {"TEXTVERIFIED_API_KEY": None}, "TEXTVERIFIED_API_KEY"),
    ("textverified without username", {"TEXTVERIFIED_API_USERNAME": ""},
     "TEXTVERIFIED_API_USERNAME"),
    ("onlinesim without api key", {"VERIFICATION_PROVIDER": "onlinesim"}, "ONLINESIM_API_KEY"),
    ("unknown verification provider", {"VERIFICATION_PROVIDER": "numbersrus"},
     "not a provider this codebase has an adapter for"),
    # An origin lock that cannot actually lock: looks protected, protects nothing.
    ("unknown cloudflare mode", {"CLOUDFLARE_MODE": "maybe"}, "must be off, report or enforce"),
    ("cloudflare lock without a secret", {"CLOUDFLARE_MODE": "enforce"},
     "CLOUDFLARE_ORIGIN_SECRET"),
    ("cloudflare lock with a short secret",
     {"CLOUDFLARE_MODE": "report", "CLOUDFLARE_ORIGIN_SECRET": "short"},
     "CLOUDFLARE_ORIGIN_SECRET"),
    ("proxy count unset", {"TRUSTED_PROXY_COUNT": None}, "TRUSTED_PROXY_COUNT"),
    # Half a Google client signs nobody in; a plain-HTTP callback carries the
    # authorisation code in the clear.
    ("google client without its secret",
     {"GOOGLE_OAUTH_CLIENT_ID": "1234.apps.googleusercontent.com"}, "GOOGLE_OAUTH_CLIENT_SECRET"),
    ("google secret without its client",
     {"GOOGLE_OAUTH_CLIENT_SECRET": "placeholder"}, "GOOGLE_OAUTH_CLIENT_ID"),
    ("google callback over http",
     {"GOOGLE_OAUTH_CLIENT_ID": "1234.apps.googleusercontent.com",
      "GOOGLE_OAUTH_CLIENT_SECRET": "placeholder",
      "GOOGLE_OAUTH_REDIRECT_URI": "http://api.verifygh.example/api/v1/auth/google/callback/"},
     "GOOGLE_OAUTH_REDIRECT_URI"),
    # Email verification gates every purchase. A backend that delivers nothing
    # does not switch that gate off, it makes it impossible to pass - while
    # every send is reported as successful. Nothing looks broken, and no
    # account can ever be verified.
    ("no email provider", {"BREVO_API_KEY": None}, "delivers nothing"),
    # A leftover Resend key does not send anything any more, and says so.
    ("only the old resend key", {"BREVO_API_KEY": None, "RESEND_API_KEY": "re_" + "0" * 30},
     "RESEND_API_KEY is no longer used"),
    ("console email backend",
     {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"}, "delivers nothing"),
    ("file email backend",
     {"EMAIL_BACKEND": "django.core.mail.backends.filebased.EmailBackend"}, "delivers nothing"),
    ("dummy email backend",
     {"EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend"}, "delivers nothing"),
    ("in-memory email backend",
     {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}, "delivers nothing"),
    # Brevo's SMTP key looks like its API key and does not work with the API.
    ("brevo smtp key instead of an api key",
     {"BREVO_API_KEY": "xsmtpsib-" + "0" * 64}, "does not look like a Brevo API key"),
    ("brevo without a sender", {"BREVO_SENDER_EMAIL": None}, "BREVO_SENDER_EMAIL is required"),
    # SMTP selected by hand, with nothing to authenticate with.
    ("smtp without credentials",
     {"EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend", "BREVO_API_KEY": None},
     "EMAIL_HOST is required"),
    # Reserved TLDs never resolve; real providers reject them outright. This is
    # the class of mistake that made Paystack refuse our charges.
    ("sender on a reserved domain",
     {"BREVO_SENDER_EMAIL": "support@verifygh.example"}, "reserved domain"),
    ("sender that is not an address",
     {"EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend", "BREVO_SENDER_EMAIL": None,
      "EMAIL_HOST": "smtp.example.org", "EMAIL_HOST_PASSWORD": "placeholder",
      "DEFAULT_FROM_EMAIL": "VerifyGH"}, "full email address"),
    # Turning the gate off would let an unverified account spend money, which is
    # the one thing email verification exists to prevent.
    ("purchase gate disabled",
     {"REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE": "false"}, "unverified accounts buy"),
    ("database without tls", {"DB_SSLMODE": "prefer"}, "DB_SSLMODE"),
    ("http frontend", {"FRONTEND_URL": "http://verifygh.example"}, "https://"),
    ("http cors origin", {"CORS_ALLOWED_ORIGINS": "http://verifygh.example"}, "https://"),
]


@pytest.mark.parametrize(("label", "changes", "message"), UNSAFE, ids=[u[0] for u in UNSAFE])
def test_production_refuses_to_boot(label, changes, message):
    result = boot(**changes)
    assert result.returncode != 0, f"{label}: booted anyway"
    assert "ImproperlyConfigured" in result.stderr
    assert message in result.stderr, result.stderr[-1500:]


def test_the_cloudflare_origin_lock_boots_with_a_strong_secret():
    result = boot(CLOUDFLARE_MODE="enforce", CLOUDFLARE_ORIGIN_SECRET="c" * 48)
    assert result.returncode == 0, result.stderr[-2000:]


def test_sign_in_with_google_boots_with_a_full_https_client():
    result = boot(
        GOOGLE_OAUTH_CLIENT_ID="1234.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="placeholder",
        GOOGLE_OAUTH_REDIRECT_URI="https://api.verifygh.example/api/v1/auth/google/callback/",
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_debug_cannot_be_switched_on_by_the_environment():
    result = boot(DEBUG="true")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "BOOTED False" in result.stdout


def test_a_dotenv_file_is_ignored_in_production(tmp_path):
    """backend/.env holds development values (VERIFICATION_PROVIDER=mock and a
    dev SECRET_KEY). Production must not read it to fill gaps: with the
    variable removed, boot fails on the missing value rather than succeeding
    on the .env one."""
    if not (BACKEND / ".env").exists():
        pytest.skip("no local .env to leak")
    result = boot(SECRET_KEY=None)
    assert result.returncode != 0
    assert "Missing required production environment variables: SECRET_KEY" in result.stderr


def test_the_safe_baseline_selects_textverified_and_never_the_mock():
    result = subprocess.run(
        [sys.executable, "-c",
         "import django; django.setup(); "
         "from apps.verification.registry import get_provider as g; "
         "p = g(); print('PROVIDER', p.key, p.is_configured)"],
        cwd=BACKEND, env={**{k: v for k, v in os.environ.items() if k not in SCRUB}, **SAFE},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "PROVIDER textverified True" in result.stdout


# ---------------------------------------------------------------------------
# Connection poolers (placeholder host and password)
# ---------------------------------------------------------------------------

SESSION_POOLER = "postgresql://app:placeholder@pooler.internal:5432/verifygh"
TRANSACTION_POOLER = SESSION_POOLER.replace(":5432/", ":6543/")


def _db_settings(**changes) -> dict:
    import json

    child_env = {key: value for key, value in os.environ.items() if key not in SCRUB}
    child_env.update(SAFE)
    child_env.update(changes)
    result = subprocess.run(
        [sys.executable, "-c",
         "import django, json; django.setup(); from django.conf import settings; "
         "db = settings.DATABASES['default']; "
         "print(json.dumps({k: db.get(k) for k in "
         "('HOST', 'PORT', 'CONN_MAX_AGE', 'DISABLE_SERVER_SIDE_CURSORS', 'OPTIONS')}))"],
        cwd=BACKEND, env=child_env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_session_pooler_keeps_persistent_connections():
    db = _db_settings(DATABASE_URL=SESSION_POOLER)
    assert db["PORT"] == "5432"
    assert db["OPTIONS"]["sslmode"] == "require"
    assert db["CONN_MAX_AGE"] == 60
    assert not db["DISABLE_SERVER_SIDE_CURSORS"]


def test_the_transaction_pooler_port_is_refused_without_the_matching_mode():
    """Port 6543 is the conventional transaction-pooler port. Booting without
    DB_POOL_MODE=transaction works until the nightly reconciliation runs."""
    result = boot(DATABASE_URL=TRANSACTION_POOLER)
    assert result.returncode != 0
    assert "DB_POOL_MODE=transaction" in result.stderr


def test_transaction_mode_disables_what_a_pooler_cannot_carry():
    db = _db_settings(DATABASE_URL=TRANSACTION_POOLER, DB_POOL_MODE="transaction")
    assert db["DISABLE_SERVER_SIDE_CURSORS"] is True
    assert db["CONN_MAX_AGE"] == 0
    assert db["OPTIONS"]["prepare_threshold"] is None


def test_an_unknown_pool_mode_is_refused():
    result = boot(DB_POOL_MODE="statement")
    assert result.returncode != 0
    assert "DB_POOL_MODE must be" in result.stderr


def test_the_health_endpoint_is_exempt_from_the_https_redirect():
    """A platform healthcheck arrives over plain HTTP on the private network,
    without X-Forwarded-Proto. If SECURE_SSL_REDIRECT answers it with a 301,
    every deployment is marked unhealthy and the previous container keeps
    serving - a failure that looks like success from the outside."""
    import re

    result = subprocess.run(
        [sys.executable, "-c",
         "import django; django.setup(); from django.conf import settings; "
         "print(settings.SECURE_SSL_REDIRECT, '|', settings.SECURE_REDIRECT_EXEMPT)"],
        cwd=BACKEND,
        env={**{k: v for k, v in os.environ.items() if k not in SCRUB}, **SAFE},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    redirect, _, exempt = result.stdout.strip().rpartition("|")

    assert "True" in redirect, "HTTPS redirect should stay on for ordinary traffic"
    patterns = re.findall(r"'([^']+)'", exempt)
    assert any(re.match(pattern, "health/") for pattern in patterns), (
        f"no exemption matches the health endpoint: {patterns}"
    )


def test_moolre_boots_with_its_live_credentials():
    result = boot(PAYMENT_PROVIDER="moolre", PAYSTACK_SECRET_KEY=None, MOOLRE_USERNAME="verifygh",
                  MOOLRE_PUBLIC_KEY="p" * 32, MOOLRE_ACCOUNT_NUMBER="10000000001",
                  MOOLRE_CALLBACK_SECRET="s" * 36)
    assert result.returncode == 0, result.stderr[-2000:]
