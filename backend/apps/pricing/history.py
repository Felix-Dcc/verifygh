"""Price history and publishing: every change to what customers are charged.

Prices move for four reasons - a provider changes its cost, the pricing FX rate
moves, staff edit a rule, staff override a price - and only some of those are
someone's decision at the time. `refresh_offering_prices` recomputes the
sellable catalogue after any of them, then:

* **auto-publish on** (the default): the new price goes live and a PriceChange
  row records old, new, cause, and who and why where a person caused it;
* **auto-publish off**: the new price becomes a *recommendation*
  (`recommended_price`, `price_review_pending`) and customers keep paying the
  published price until staff review and `publish_prices`.

A staff override is a decision in itself, so it is published straight away in
either mode.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ProviderService
from apps.pricing.engine import NoPricingRule, quote_many
from apps.pricing.models import PriceChange, PriceChangeSource, PricingPolicy

logger = logging.getLogger("verifygh.pricing")


def _change(offering, *, old, new, quote, source, actor, reason) -> PriceChange:
    return PriceChange(
        offering=offering,
        service_name=offering.service.name[:80],
        country_code=offering.country.code,
        provider_key=offering.provider.adapter_key,
        old_price=old,
        new_price=new,
        calculated_price=quote.calculated_price if quote.calculated_price != new else None,
        currency=quote.currency,
        provider_cost=quote.provider_cost,
        provider_currency=quote.provider_currency,
        exchange_rate=quote.exchange_rate,
        pricing_rule_name=quote.pricing_rule_name[:80],
        source=source,
        changed_by=actor,
        reason=(reason or "")[:500],
    )


def _offerings(ids=None):
    from apps.catalog.marketplace import sellable_offerings

    queryset = sellable_offerings().select_related("service", "country", "provider")
    if ids is not None:
        queryset = queryset.filter(pk__in=list(ids))
    return list(queryset)


def refresh_offering_prices(*, source: str, reason: str = "", actor=None, offering_ids=None,
                            force_publish: bool = False) -> dict:
    """Recompute sellable prices; publish or queue them according to the policy.

    `force_publish` publishes regardless of the policy - used for overrides,
    which are staff decisions and never wait for review.
    """
    offerings = _offerings(offering_ids)
    try:
        quotes = quote_many(offerings, published=False)
    except NoPricingRule:
        logger.warning("price_refresh_skipped_no_rule")
        return {"priced": 0, "changed": 0, "pending": 0}

    auto = force_publish or PricingPolicy.get().auto_publish_prices
    now = timezone.now()
    changes: list[PriceChange] = []
    updates: list[ProviderService] = []
    pending = 0

    for offering in offerings:
        quote = quotes.get(str(offering.pk))
        if quote is None:
            continue
        recommended = quote.recommended_price
        current = offering.customer_price
        fields_before = (offering.recommended_price, offering.price_review_pending, current)

        if current is None:
            # First price we ever record: nothing to review it against.
            changes.append(_change(offering, old=None, new=recommended, quote=quote,
                                   source=PriceChangeSource.INITIAL, actor=None, reason=""))
            offering.customer_price, offering.price_updated_at = recommended, now
            offering.price_review_pending = False
        elif auto:
            if current != recommended:
                changes.append(_change(offering, old=current, new=recommended, quote=quote,
                                       source=source, actor=actor, reason=reason))
                offering.customer_price, offering.price_updated_at = recommended, now
            offering.price_review_pending = False
        else:
            offering.price_review_pending = current != recommended
            pending += offering.price_review_pending
        offering.recommended_price = recommended

        if (offering.recommended_price, offering.price_review_pending,
                offering.customer_price) != fields_before:
            updates.append(offering)

    if updates:
        with transaction.atomic():
            PriceChange.objects.bulk_create(changes)
            ProviderService.objects.bulk_update(
                updates,
                ["customer_price", "price_updated_at", "recommended_price", "price_review_pending"],
            )
        from apps.catalog import marketplace

        marketplace.invalidate()

    logger.info("offering_prices_refreshed",
                extra={"source": source, "priced": len(quotes), "changed": len(changes),
                       "pending": pending})
    return {"priced": len(quotes), "changed": len(changes), "pending": pending}


def publish_prices(*, actor, reason: str, offering_ids=None) -> dict:
    """Publish reviewed recommendations. `offering_ids=None` publishes all pending."""
    queryset = ProviderService.objects.filter(price_review_pending=True)
    if offering_ids is not None:
        queryset = queryset.filter(pk__in=list(offering_ids))
    ids = list(queryset.values_list("pk", flat=True))
    if not ids:
        return {"published": 0}

    offerings = _offerings(ids)
    quotes = quote_many(offerings, published=False)
    now = timezone.now()
    changes, updates = [], []
    for offering in offerings:
        quote = quotes.get(str(offering.pk))
        if quote is None:
            continue
        new: Decimal = quote.recommended_price
        if offering.customer_price != new:
            changes.append(_change(offering, old=offering.customer_price, new=new, quote=quote,
                                   source=PriceChangeSource.PUBLISHED, actor=actor, reason=reason))
        offering.customer_price, offering.price_updated_at = new, now
        offering.recommended_price, offering.price_review_pending = new, False
        updates.append(offering)

    with transaction.atomic():
        PriceChange.objects.bulk_create(changes)
        ProviderService.objects.bulk_update(
            updates,
            ["customer_price", "price_updated_at", "recommended_price", "price_review_pending"],
        )
    from apps.catalog import marketplace

    marketplace.invalidate()
    return {"published": len(changes)}
