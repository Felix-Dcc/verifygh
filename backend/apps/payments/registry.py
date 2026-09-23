"""Payment provider registry.

Adding Hubtel, Flutterwave or a direct MNO integration means writing one adapter
and registering it here. Nothing in `apps/wallet`, `apps/orders` or the API layer
changes.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.common.errors import ServiceUnavailable
from apps.payments.base import PaymentProvider
from apps.payments.hubtel import HubtelProvider
from apps.payments.mock import MockPaymentProvider
from apps.payments.paystack import PaystackProvider

logger = logging.getLogger("verifygh.payments")

_REGISTRY: dict[str, type[PaymentProvider]] = {
    MockPaymentProvider.key: MockPaymentProvider,
    PaystackProvider.key: PaystackProvider,
    # Registered so it can be selected and tested, but its endpoints are blank
    # until the official documentation is in hand - see hubtel.py.
    HubtelProvider.key: HubtelProvider,
}


def register(adapter: type[PaymentProvider]) -> type[PaymentProvider]:
    _REGISTRY[adapter.key] = adapter
    return adapter


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)


def get_payment_provider(key: str | None = None) -> PaymentProvider:
    provider_key = key or settings.VERIFYGH["PAYMENT_PROVIDER"]
    adapter = _REGISTRY.get(provider_key)
    if adapter is None:
        logger.error("unknown_payment_adapter", extra={"adapter_key": provider_key})
        raise ServiceUnavailable(
            "Payments are temporarily unavailable.", code="UNKNOWN_PAYMENT_PROVIDER"
        )
    return adapter()


def webhook_providers() -> set[str]:
    """Providers allowed to deliver callbacks.

    Every registered adapter is importable, but only the active provider (plus
    any explicitly listed for a switchover) may have its webhook endpoint
    reached. Leaving the mock adapter's endpoint live in production would let
    anyone who knows its default secret confirm payments that never happened.
    """
    enabled = {settings.VERIFYGH["PAYMENT_PROVIDER"]}
    enabled.update(key for key in settings.VERIFYGH.get("WEBHOOK_PROVIDERS", []) if key)
    return {key for key in enabled if key in _REGISTRY}
