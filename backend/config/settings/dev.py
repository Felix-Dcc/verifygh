"""Local development settings: safe defaults, loud errors, no real money."""

from .base import *  # noqa: F401,F403
from .base import VERIFYGH, env_bool

DEBUG = True
ALLOWED_HOSTS = ["*"]

AUTH_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Run tasks inline unless a real broker is configured, so the app works with
# nothing but `runserver`.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)

VERIFYGH = {**VERIFYGH, "VERIFICATION_PROVIDER": "mock", "PAYMENT_PROVIDER": "mock",
            "STAFF_TWO_FACTOR_REQUIRED": env_bool("STAFF_TWO_FACTOR_REQUIRED", False)}
