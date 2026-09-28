"""Exchange-rate abstraction.

The rate is never hardcoded. In development an admin types it in; in production
a rate provider fetches it on a schedule. Both go through the same interface, so
switching is one environment variable.
"""

from __future__ import annotations

import abc
import logging
from decimal import Decimal

from django.conf import settings

from apps.common.errors import ServiceUnavailable
from apps.pricing.models import ExchangeRate

logger = logging.getLogger("verifygh.pricing")

# How stale a rate may be before we refuse to quote with it. Pricing off a
# week-old cedi rate is a good way to sell below cost.
MAX_RATE_AGE_HOURS = 36


class ExchangeRateProvider(abc.ABC):
    key: str = "base"

    @abc.abstractmethod
    def fetch(self, base: str, quote: str) -> Decimal:
        """Return the current `quote` units per 1 `base` unit."""


class ManualExchangeRateProvider(ExchangeRateProvider):
    """Uses whatever an admin last entered. The development default."""

    key = "manual"

    def fetch(self, base: str, quote: str) -> Decimal:
        rate = latest_rate_row(base, quote)
        if rate is None:
            raise ServiceUnavailable(
                "No exchange rate has been configured yet.", code="NO_EXCHANGE_RATE"
            )
        return rate.rate


class ApiExchangeRateProvider(ExchangeRateProvider):
    """Fetches from an external FX API.

    TODO(credentials): set EXCHANGE_RATE_API_URL and EXCHANGE_RATE_API_KEY, and
    adjust `_parse` to match your chosen provider's response shape. No endpoint
    is assumed here.
    """

    key = "api"

    def fetch(self, base: str, quote: str) -> Decimal:
        import os

        import requests

        url = os.environ.get("EXCHANGE_RATE_API_URL", "")
        api_key = settings.EXCHANGE_RATE_API_KEY

        if not url or not api_key:
            raise ServiceUnavailable(
                "The exchange-rate provider is not configured.", code="NO_EXCHANGE_RATE"
            )

        response = requests.get(
            url,
            params={"base": base, "symbols": quote},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        return self._parse(response.json(), quote)

    @staticmethod
    def _parse(payload: dict, quote: str) -> Decimal:
        # TODO(credentials): match your provider's JSON shape.
        rates = payload.get("rates") or payload.get("data") or {}
        value = rates.get(quote)
        if value is None:
            raise ServiceUnavailable(
                "The exchange-rate response did not include GHS.", code="NO_EXCHANGE_RATE"
            )
        return Decimal(str(value))


_PROVIDERS: dict[str, type[ExchangeRateProvider]] = {
    ManualExchangeRateProvider.key: ManualExchangeRateProvider,
    ApiExchangeRateProvider.key: ApiExchangeRateProvider,
}


def get_rate_provider() -> ExchangeRateProvider:
    key = settings.VERIFYGH["EXCHANGE_RATE_PROVIDER"]
    provider_class = _PROVIDERS.get(key)
    if provider_class is None:
        raise ServiceUnavailable(f"Unknown exchange rate provider: {key}")
    return provider_class()


def latest_rate_row(base: str = "USD", quote: str = "GHS") -> ExchangeRate | None:
    return (
        ExchangeRate.objects.filter(
            base_currency=base, quote_currency=quote, is_active=True
        )
        .order_by("-fetched_at", "-id")
        .first()
    )


def current_rate(base: str = "USD", quote: str = "GHS", allow_stale: bool = False) -> ExchangeRate:
    """The rate row to price with. Raises rather than guessing."""
    from datetime import timedelta

    from django.utils import timezone

    row = latest_rate_row(base, quote)
    if row is None:
        raise ServiceUnavailable(
            "Pricing is temporarily unavailable. Please try again shortly.",
            code="NO_EXCHANGE_RATE",
        )

    age_limit = timezone.now() - timedelta(hours=MAX_RATE_AGE_HOURS)
    if row.fetched_at < age_limit and not allow_stale:
        logger.error(
            "exchange_rate_stale",
            extra={"rate_id": str(row.id), "fetched_at": row.fetched_at.isoformat()},
        )
        raise ServiceUnavailable(
            "Pricing is temporarily unavailable. Please try again shortly.",
            code="STALE_EXCHANGE_RATE",
        )
    return row


def record_rate(rate: Decimal, *, base: str = "USD", quote: str = "GHS", source: str = "manual",
                note: str = "", actor=None) -> ExchangeRate:
    """Append a new rate row. Existing rows are never edited.

    A new rate moves every customer price, so once it has committed the
    marketplace is repriced and the changes written to price history.
    """
    from django.db import transaction

    row = ExchangeRate.objects.create(
        base_currency=base, quote_currency=quote, rate=rate, source=source, note=note
    )

    def _reprice():
        from apps.catalog import marketplace
        from apps.pricing.history import refresh_offering_prices
        from apps.pricing.models import PriceChangeSource

        marketplace.invalidate()
        refresh_offering_prices(
            source=PriceChangeSource.EXCHANGE_RATE, actor=actor,
            reason=note or f"Exchange rate set to {rate} ({source})",
        )

    transaction.on_commit(_reprice)
    return row


def refresh_rate(base: str = "USD", quote: str = "GHS") -> ExchangeRate | None:
    provider = get_rate_provider()
    if isinstance(provider, ManualExchangeRateProvider):
        return latest_rate_row(base, quote)
    try:
        value = provider.fetch(base, quote)
    except Exception:
        logger.exception("exchange_rate_refresh_failed", extra={"provider": provider.key})
        return None
    return record_rate(value, base=base, quote=quote, source=provider.key)
