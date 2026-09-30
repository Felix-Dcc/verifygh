"""Provider registry and the upstream call budget.

Two jobs:

1. Resolve `VERIFICATION_PROVIDER` (or a Provider row's `adapter_key`) to a
   concrete adapter instance. This is the seam that lets a provider be swapped
   without touching orders, wallet or the API.
2. Enforce a hard ceiling on calls to any upstream provider. We are a good
   client: we stay inside the provider's limits by construction rather than
   discovering them by getting blocked.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache

from apps.common.errors import ServiceUnavailable
from apps.verification.base import VerificationProvider
from apps.verification.mock import MockVerificationProvider
from apps.verification.onlinesim import OnlineSimProvider
from apps.verification.textverified import TextVerifiedProvider

logger = logging.getLogger("verifygh.provider")

#: Adapters that exist. Being registered is not permission to sell: a
#: provider's catalogue row must also be enabled and carry a recorded resale
#: authorisation (`Provider.resale_authorized`) before anything is listed or
#: charged through it - see orders.services.candidate_offerings.
#:
#: TextVerified is the intended primary provider. Its terms prohibit sharing
#: numbers with third parties, so it stays unauthorised until TextVerified
#: agrees in writing (docs/PROVIDERS.md). OnlineSim was the provider until
#: 2026-09-29; its adapter stays so orders made through it keep their history
#: and could still be settled, but its row is switched off.
_REGISTRY: dict[str, type[VerificationProvider]] = {
    MockVerificationProvider.key: MockVerificationProvider,
    TextVerifiedProvider.key: TextVerifiedProvider,
    OnlineSimProvider.key: OnlineSimProvider,
}


def register(adapter: type[VerificationProvider]) -> type[VerificationProvider]:
    """Decorator for adding a provider adapter."""
    _REGISTRY[adapter.key] = adapter
    return adapter


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(adapter_key: str | None = None) -> VerificationProvider:
    key = adapter_key or settings.VERIFYGH["VERIFICATION_PROVIDER"]
    adapter = _REGISTRY.get(key)
    if adapter is None:
        logger.error("unknown_provider_adapter", extra={"adapter_key": key})
        raise ServiceUnavailable(
            "Verification is temporarily unavailable.", code="UNKNOWN_PROVIDER"
        )
    return RateLimitedProvider(adapter())


STATS_TTL = 60 * 60 * 24 * 7


def _stats_key(provider_key: str) -> str:
    return f"provider_stats:{provider_key}"


def record_call(provider_key: str, operation: str, elapsed_ms: float,
                failure: Exception | None) -> None:
    """Keep a small running record of upstream calls, for the admin Providers page.

    Read-modify-write through the cache, so two simultaneous calls can drop an
    update: good enough for "when did it last work, and how fast is it", which
    is all it is used for. Never raises. Stores the error *class and code*,
    never a message body - provider responses do not reach staff screens raw.
    """
    try:
        now = time.time()
        stats = cache.get(_stats_key(provider_key)) or {"since": now, "calls": 0, "failures": 0}
        stats["calls"] = stats.get("calls", 0) + 1
        previous = stats.get("avg_ms")
        stats["avg_ms"] = elapsed_ms if previous is None else previous * 0.9 + elapsed_ms * 0.1
        if failure is None:
            stats["last_success_at"] = now
            stats["last_success_operation"] = operation
        else:
            stats["failures"] = stats.get("failures", 0) + 1
            stats["last_failure_at"] = now
            stats["last_failure_operation"] = operation
            code = getattr(failure, "provider_code", "") or getattr(failure, "code", "")
            stats["last_failure_error"] = f"{failure.__class__.__name__} {code}".strip()[:80]
        cache.set(_stats_key(provider_key), stats, STATS_TTL)
    except Exception:
        logger.warning("provider_stats_unavailable", extra={"provider": provider_key})


def call_stats(provider_key: str) -> dict:
    try:
        return cache.get(_stats_key(provider_key)) or {}
    except Exception:
        return {}


def get_default_provider_row():
    """The catalog Provider row matching the configured adapter.

    Returns None before the catalog has been seeded.
    """
    from apps.catalog.models import Provider

    return Provider.objects.filter(
        adapter_key=settings.VERIFYGH["VERIFICATION_PROVIDER"], is_enabled=True
    ).first()


class ProviderRateLimiter:
    """Fixed-window counter, shared across processes via the cache.

    Deliberately conservative: when the cache is unavailable we allow the call
    rather than blocking the platform, but we log it, because a silent loss of
    rate limiting is worth knowing about.
    """

    def __init__(self, key: str, limit_per_minute: int):
        self.key = key
        self.limit = max(1, limit_per_minute)

    def check(self) -> None:
        window = int(time.time() // 60)
        cache_key = f"provider_rl:{self.key}:{window}"
        try:
            added = cache.add(cache_key, 1, timeout=120)
            count = 1 if added else cache.incr(cache_key)
        except Exception:
            logger.warning("provider_rate_limiter_unavailable", extra={"provider": self.key})
            return

        if count > self.limit:
            logger.warning(
                "provider_call_budget_exceeded",
                extra={"provider": self.key, "count": count, "limit": self.limit},
            )
            raise ServiceUnavailable(
                "We are briefly at capacity with our provider. Please try again in a moment.",
                code="PROVIDER_BUDGET_EXCEEDED",
            )


class RateLimitedProvider(VerificationProvider):
    """Transparent wrapper that budgets every upstream call.

    Delegates the whole interface, so callers cannot accidentally reach past it.
    """

    def __init__(self, inner: VerificationProvider):
        super().__init__(inner.config)
        self._inner = inner
        self.key = inner.key
        self.display_name = inner.display_name
        self.permits_code_display = inner.permits_code_display
        self.supports_webhooks = inner.supports_webhooks
        self.supports_issue_reports = inner.supports_issue_reports
        self.supports_balance = inner.supports_balance
        self.supports_reuse = inner.supports_reuse
        self.supports_account_funding = inner.supports_account_funding
        self._limiter = ProviderRateLimiter(
            inner.key, settings.VERIFYGH["PROVIDER_RATE_LIMIT_PER_MINUTE"]
        )

    @property
    def is_configured(self) -> bool:
        return self._inner.is_configured

    @property
    def accepts_webhooks(self) -> bool:
        return self._inner.accepts_webhooks

    def parse_webhook(self, raw_body: bytes, headers: dict):
        # Local signature check, no upstream call: not budgeted.
        return self._inner.parse_webhook(raw_body, headers)

    def _call(self, name: str, *args, **kwargs):
        self._limiter.check()
        started = time.monotonic()
        failure: Exception | None = None
        try:
            return getattr(self._inner, name)(*args, **kwargs)
        except Exception as exc:
            failure = exc
            raise
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.info(
                "provider_call",
                extra={"provider": self.key, "operation": name, "ms": round(elapsed_ms)},
            )
            record_call(self.key, name, elapsed_ms, failure)

    def get_services(self, *, priority=None, time_budget=None):
        return self._call("get_services", priority=priority, time_budget=time_budget)

    def get_countries(self):
        return self._call("get_countries")

    def get_pricing(self, service_code: str, country_code: str):
        return self._call("get_pricing", service_code, country_code)

    def get_availability(self, service_code: str, country_code: str):
        return self._call("get_availability", service_code, country_code)

    def create_order(self, service_code: str, country_code: str, idempotency_key: str):
        return self._call("create_order", service_code, country_code, idempotency_key)

    def get_order_status(self, provider_order_id: str):
        return self._call("get_order_status", provider_order_id)

    def get_verification_code(self, provider_order_id: str):
        return self._call("get_verification_code", provider_order_id)

    def cancel_order(self, provider_order_id: str):
        return self._call("cancel_order", provider_order_id)

    def refund_order(self, provider_order_id: str):
        return self._call("refund_order", provider_order_id)

    def report_number_issue(self, provider_order_id: str, reason: str):
        if not self._inner.supports_issue_reports:
            return None
        return self._call("report_number_issue", provider_order_id, reason)

    def check_number_reuse(self, provider_order_id: str, service_code: str):
        return self._inner.check_number_reuse(provider_order_id, service_code)

    def release_retry_after_seconds(self, service_code: str) -> int:
        return self._inner.release_retry_after_seconds(service_code)

    def reuse_order(self, provider_order_id: str, idempotency_key: str):
        if not self._inner.supports_reuse:
            raise NotImplementedError(f"{self.display_name} documents no number reuse.")
        return self._call("reuse_order", provider_order_id, idempotency_key)

    def get_balance(self):
        if not self._inner.supports_balance:
            return None
        return self._call("get_balance")

    def fund_account(self, amount, currency: str, reference: str):
        if not self._inner.supports_account_funding:
            raise NotImplementedError(
                f"{self.display_name} documents no API for funding our account."
            )
        return self._call("fund_account", amount, currency, reference)

    def health_check(self) -> bool:
        return self._inner.health_check()
