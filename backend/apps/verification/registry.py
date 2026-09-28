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

logger = logging.getLogger("verifygh.provider")

#: OnlineSim is the only supplier. TextVerified is deliberately absent: it
#: refused resale permission, so nothing may sync its catalogue, reserve a
#: number from it or health-check it. `apps/verification/textverified.py` stays
#: as a documented reference, reachable only by importing it directly - which
#: is what its endpoint-provenance tests do.
_REGISTRY: dict[str, type[VerificationProvider]] = {
    MockVerificationProvider.key: MockVerificationProvider,
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
        self._limiter = ProviderRateLimiter(
            inner.key, settings.VERIFYGH["PROVIDER_RATE_LIMIT_PER_MINUTE"]
        )

    def _call(self, name: str, *args, **kwargs):
        self._limiter.check()
        started = time.monotonic()
        try:
            return getattr(self._inner, name)(*args, **kwargs)
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.info(
                "provider_call",
                extra={"provider": self.key, "operation": name, "ms": round(elapsed_ms)},
            )

    def get_services(self):
        return self._call("get_services")

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

    def health_check(self) -> bool:
        return self._inner.health_check()
