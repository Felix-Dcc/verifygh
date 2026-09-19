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
    "WEBHOOK_PROVIDERS": "",
    "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION": "",
    "ALLOW_PAYSTACK_TEST_KEYS": "",
    "ALLOW_UNENCRYPTED_DATABASE": "",
}

#: Variables that must not leak in from the developer's shell.
SCRUB = set(SAFE) | {"DEBUG", "MOCK_PAYMENT_SECRET", "REQUIRE_POSTGRES"}


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
    ("paystack without key", {"PAYSTACK_SECRET_KEY": None}, "PAYSTACK_SECRET_KEY is required"),
    ("paystack test key", {"PAYSTACK_SECRET_KEY": "sk_test_" + "0" * 40}, "not a live key"),
    ("paystack public key", {"PAYSTACK_SECRET_KEY": "pk_live_" + "0" * 40}, "public key"),
    ("mock webhook route", {"WEBHOOK_PROVIDERS": "mock"}, "must not include 'mock'"),
    ("mock verification", {"VERIFICATION_PROVIDER": "mock"}, "simulated numbers"),
    ("proxy count unset", {"TRUSTED_PROXY_COUNT": None}, "TRUSTED_PROXY_COUNT"),
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


def test_textverified_is_inert_in_the_safe_baseline():
    """The production default sells nothing until an authorised provider is
    configured from official documentation."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import django; django.setup(); "
         "from apps.verification.registry import get_provider as g; "
         "p = g('textverified'); print('CONFIGURED', p.health_check())"],
        cwd=BACKEND, env={**{k: v for k, v in os.environ.items() if k not in SCRUB}, **SAFE},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "CONFIGURED False" in result.stdout
