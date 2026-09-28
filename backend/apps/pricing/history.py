"""Price history: write down every change to what customers are charged.

Prices are computed live, from provider cost x exchange rate through the
pricing rule, so they change for three reasons - a staff edit to a rule, a
provider changing its price, a new exchange rate - and only the first leaves an
AdminAction behind. `refresh_offering_prices` recomputes the sellable catalogue
after any of the three and records one PriceChange per offering that moved,
with who and why where a person caused it.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ProviderService
from apps.pricing.engine import NoPricingRule, quote_many
from apps.pricing.models import PriceChange, PriceChangeSource

logger = logging.getLogger("verifygh.pricing")


def refresh_offering_prices(*, source: str, reason: str = "", actor=None) -> dict:
    """Recompute sellable prices and record those that changed.

    Only the marketplace countries are priced: those are the only prices a
    customer can see, and the full provider catalogue is tens of thousands of
    rows nobody is charged.
    """
    from apps.catalog.marketplace import sellable_offerings

    offerings = list(sellable_offerings().select_related("service", "country", "provider"))
    try:
        quotes = quote_many(offerings)
    except NoPricingRule:
        logger.warning("price_refresh_skipped_no_rule")
        return {"priced": 0, "changed": 0}

    now = timezone.now()
    changes: list[PriceChange] = []
    updates: list[ProviderService] = []
    for offering in offerings:
        quote = quotes.get(str(offering.pk))
        if quote is None or offering.customer_price == quote.customer_price:
            continue
        first = offering.customer_price is None
        changes.append(PriceChange(
            offering=offering,
            service_name=offering.service.name[:80],
            country_code=offering.country.code,
            provider_key=offering.provider.adapter_key,
            old_price=offering.customer_price,
            new_price=quote.customer_price,
            currency=quote.currency,
            provider_cost=quote.provider_cost,
            provider_currency=quote.provider_currency,
            exchange_rate=quote.exchange_rate,
            pricing_rule_name=quote.pricing_rule_name[:80],
            source=PriceChangeSource.INITIAL if first else source,
            changed_by=None if first else actor,
            reason=("" if first else reason)[:500],
        ))
        offering.customer_price = quote.customer_price
        offering.price_updated_at = now
        updates.append(offering)

    if changes:
        with transaction.atomic():
            PriceChange.objects.bulk_create(changes)
            ProviderService.objects.bulk_update(updates, ["customer_price", "price_updated_at"])

    logger.info("offering_prices_refreshed",
                extra={"source": source, "priced": len(quotes), "changed": len(changes)})
    return {"priced": len(quotes), "changed": len(changes)}
