"""Test settings: fast hashing, eager tasks, in-memory cache."""

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, VERIFYGH

DEBUG = False
SECRET_KEY = "test-only-secret-key-long-enough-for-hmac-sha256-0000"

# WhiteNoise warns on every request when STATIC_ROOT is missing; tests never
# run collectstatic.
STATIC_ROOT.mkdir(exist_ok=True)  # noqa: F405

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "verifygh-tests",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Off unless a test turns them on: a developer's .env must not make every
# sign-in in the suite call Cloudflare or Google.
TURNSTILE_SECRET_KEY = ""
TURNSTILE_ALLOWED_HOSTNAMES: list[str] = []
GOOGLE_OAUTH_CLIENT_ID = ""
GOOGLE_OAUTH_CLIENT_SECRET = ""
GOOGLE_OAUTH_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback/"

# The concurrency tests run real threads against real connections. SQLite's
# default in-memory test database cannot serialise those, so use a file with a
# busy timeout. On PostgreSQL none of this applies - row locks do the work.
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):  # noqa: F405
    DATABASES["default"]["TEST"] = {"NAME": str(BASE_DIR / "test_db.sqlite3")}  # noqa: F405
    DATABASES["default"].setdefault("OPTIONS", {})  # noqa: F405
    DATABASES["default"]["OPTIONS"]["timeout"] = 30  # noqa: F405
    DATABASES["default"]["ENGINE"] = "config.sqlite_immediate"  # noqa: F405

VERIFYGH = {
    **VERIFYGH,
    "VERIFICATION_PROVIDER": "mock",
    "PAYMENT_PROVIDER": "mock",
    "ORDER_TTL_MINUTES": 10,
    # Off by default so that tests about webhooks, the ledger and refunds do not
    # each have to stock a catalogue to be allowed to deposit - they are about
    # money movement, not marketplace readiness.
    #
    # tests/test_deposit_guard.py turns it back on and covers it properly, and
    # asserts separately that production ships with it enabled.
    "REQUIRE_CATALOG_FOR_DEPOSIT": False,
}

LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405

# base.py builds REST_FRAMEWORK from the *environment's* DEBUG, before this
# module sets DEBUG = False. Pin JSON-only here so the browsable API can never
# be switched back on by a stray DEBUG=true in the deploy environment.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
