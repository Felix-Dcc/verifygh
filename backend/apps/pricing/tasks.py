from __future__ import annotations

import logging

from celery import shared_task

from apps.pricing.rates import refresh_rate

logger = logging.getLogger("verifygh.pricing")


@shared_task(name="apps.pricing.tasks.refresh_exchange_rate")
def refresh_exchange_rate() -> str | None:
    """Append today's USD/GHS rate.

    Returns None when the provider is manual or the fetch failed; the existing
    rate keeps being used until it goes stale, at which point quoting stops
    rather than pricing off a bad number.
    """
    row = refresh_rate("USD", "GHS")
    if row is None:
        logger.warning("exchange_rate_not_refreshed")
        return None
    logger.info("exchange_rate_refreshed", extra={"rate": str(row.rate)})
    return str(row.id)
