"""Catalog synchronisation.

The catalog is *derived* from the provider, never typed in. A sync pulls the
provider's services, countries, costs and availability and upserts them. Our own
`is_enabled` flags are never overwritten by a sync - if an admin disabled a
service, a provider refresh must not silently re-enable it.

Presentation metadata (category, accent colour) is ours, because providers do
not supply it. Note what is deliberately absent: brand logo files. We render a
lettermark in the service's accent colour rather than redistributing third-party
trademarks.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

from apps.catalog.models import Country, Provider, ProviderService, Service, ServiceCategory
from apps.verification.registry import get_provider

logger = logging.getLogger("verifygh.catalog")

#: Presentation-only metadata: (category, accent colour).
SERVICE_METADATA: dict[str, tuple[str, str]] = {
    "instagram": (ServiceCategory.SOCIAL, "#C13584"),
    "facebook": (ServiceCategory.SOCIAL, "#1877F2"),
    "tiktok": (ServiceCategory.SOCIAL, "#111111"),
    "x": (ServiceCategory.SOCIAL, "#14171A"),
    "twitter": (ServiceCategory.SOCIAL, "#14171A"),
    "linkedin": (ServiceCategory.BUSINESS, "#0A66C2"),
    "whatsapp": (ServiceCategory.MESSAGING, "#25D366"),
    "telegram": (ServiceCategory.MESSAGING, "#229ED9"),
    "signal": (ServiceCategory.MESSAGING, "#3A76F0"),
    "discord": (ServiceCategory.MESSAGING, "#5865F2"),
    "google": (ServiceCategory.EMAIL, "#4285F4"),
    "github": (ServiceCategory.DEVELOPER, "#24292F"),
    "openai": (ServiceCategory.DEVELOPER, "#10A37F"),
    "amazon": (ServiceCategory.BUSINESS, "#FF9900"),
    "uber": (ServiceCategory.BUSINESS, "#0E0E0E"),
    "airbnb": (ServiceCategory.BUSINESS, "#FF5A5F"),
    "paypal": (ServiceCategory.FINANCE, "#003087"),
}

COUNTRY_FLAGS = {
    "US": "\U0001F1FA\U0001F1F8",
    "GB": "\U0001F1EC\U0001F1E7",
    "CA": "\U0001F1E8\U0001F1E6",
    "NL": "\U0001F1F3\U0001F1F1",
    "DE": "\U0001F1E9\U0001F1EA",
    "FR": "\U0001F1EB\U0001F1F7",
    "ES": "\U0001F1EA\U0001F1F8",
    "GH": "\U0001F1EC\U0001F1ED",
    "NG": "\U0001F1F3\U0001F1EC",
    "KE": "\U0001F1F0\U0001F1EA",
    "ZA": "\U0001F1FF\U0001F1E6",
}


def marketplace_readiness() -> dict:
    """Can the marketplace actually sell anything right now?

    Four things have to be true together, and each fails differently: a provider
    must be configured, an exchange rate must exist to price in cedis, at least
    one offering must be purchasable, and that offering must actually price.

    The last one was learned the hard way. Counting purchasable rows said the
    marketplace was open while every single purchase raised NoPricingRule,
    because no pricing rule existed - so deposits were accepted into a shop
    where nothing could be bought. An offering nobody can be quoted a price for
    is not stock, and readiness has to mean "a customer can complete a
    purchase", not "rows exist".

    Deliberately one function rather than a query repeated wherever the question
    comes up. The landing page, the deposit guard and the admin health panel all
    need the same answer, and three copies of it would drift until they
    disagreed - at which point we would be taking money on one screen while
    another said the shop was shut.
    """
    from apps.pricing.rates import latest_rate_row
    from apps.verification.registry import get_default_provider_row

    provider_row = get_default_provider_row()
    rate = latest_rate_row()
    purchasable = ProviderService.objects.filter(
        is_enabled=True,
        is_available=True,
        provider__is_enabled=True,
        service__is_enabled=True,
        country__is_enabled=True,
    ).count()

    # Prove it by pricing one, rather than trusting that a rule exists and
    # covers this offering: rules are scoped by service and country, so a rule
    # that matches nothing is the same as no rule at all.
    priceable = False
    if purchasable and rate is not None:
        priceable = _cheapest_offering_prices()

    return {
        "ready": bool(provider_row and rate and purchasable and priceable),
        "provider_configured": provider_row is not None,
        "exchange_rate_configured": rate is not None,
        "purchasable_offerings": purchasable,
        "pricing_configured": priceable,
    }


def _cheapest_offering_prices() -> bool:
    """Can we actually quote a customer for something?

    One offering, not all of them: this runs on the deposit screen and the
    landing page, and pricing sixty rows to answer "are we open" would be
    wasteful. If the cheapest prices, a pricing rule exists and matches.
    """
    from apps.pricing.engine import NoPricingRule, quote_for_offering

    offering = (
        ProviderService.objects.filter(
            is_enabled=True,
            is_available=True,
            provider__is_enabled=True,
            service__is_enabled=True,
            country__is_enabled=True,
        )
        .select_related("service", "country", "provider")
        .order_by("cost_amount")
        .first()
    )
    if offering is None:
        return False

    try:
        quote_for_offering(offering)
    except NoPricingRule:
        logger.warning("no_pricing_rule_matches_catalogue")
        return False
    except Exception:
        # Any other pricing failure is still a customer who cannot buy.
        logger.exception("pricing_check_failed")
        return False
    return True


def ensure_provider_row(adapter_key: str) -> Provider:
    provider, created = Provider.objects.get_or_create(
        adapter_key=adapter_key,
        defaults={"name": adapter_key.title(), "is_enabled": True},
    )
    if created:
        logger.info("provider_row_created", extra={"adapter_key": adapter_key})
    return provider


def sync_catalog(adapter_key: str | None = None) -> dict:
    """Pull the provider catalogue and upsert it.

    Returns a summary so the admin UI and the Celery log can both show what
    changed.
    """
    provider_client = get_provider(adapter_key)
    provider_row = ensure_provider_row(provider_client.key)

    summary = {
        "provider": provider_client.key,
        "countries": 0,
        "services": 0,
        "offerings": 0,
        "unavailable": 0,
        "errors": [],
    }

    try:
        provider_countries = provider_client.get_countries()
        provider_services = provider_client.get_services()
    except Exception as exc:
        message = f"{exc.__class__.__name__}: {exc}"
        logger.exception("catalog_sync_failed", extra={"provider": provider_client.key})
        Provider.objects.filter(pk=provider_row.pk).update(
            last_sync_error=message[:2000], last_synced_at=timezone.now()
        )
        summary["errors"].append(message)
        return summary

    country_rows: dict[str, Country] = {}
    for dto in provider_countries:
        code = dto.code.upper()
        country, created = Country.objects.get_or_create(
            code=code,
            defaults={
                "name": dto.name,
                "dial_code": dto.dial_code,
                "flag_emoji": COUNTRY_FLAGS.get(code, ""),
            },
        )
        # Refresh provider-owned fields only; is_enabled stays ours.
        updates = {}
        if country.name != dto.name and dto.name:
            updates["name"] = dto.name
        if dto.dial_code and country.dial_code != dto.dial_code:
            updates["dial_code"] = dto.dial_code
        if not country.flag_emoji and COUNTRY_FLAGS.get(code):
            updates["flag_emoji"] = COUNTRY_FLAGS[code]
        if updates:
            Country.objects.filter(pk=country.pk).update(**updates)
            country.refresh_from_db()

        country_rows[code] = country
        summary["countries"] += 1 if created else 0

    service_rows: dict[str, Service] = {}
    for dto in provider_services:
        slug = dto.code.lower()
        if slug not in service_rows:
            from apps.catalog.presentation import PRESENTATION, bundled_icon_url

            category, accent = SERVICE_METADATA.get(slug, (ServiceCategory.OTHER, "#0F766E"))
            name, aliases, category, rank = PRESENTATION.get(
                slug, (dto.name, "", category, None)
            )
            service, created = Service.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "aliases": aliases,
                    "category": category,
                    "accent_color": accent,
                    "icon_url": bundled_icon_url(slug),
                    "is_popular": rank is not None,
                    "popular_rank": rank or 100,
                    "supports_sms": dto.supports_sms,
                    "supports_voice": dto.supports_voice,
                },
            )
            service_rows[slug] = service
            summary["services"] += 1 if created else 0

    for dto in provider_services:
        slug = dto.code.lower()
        code = dto.country_code.upper()
        service = service_rows.get(slug)
        country = country_rows.get(code)
        if service is None or country is None:
            continue

        offering, created = ProviderService.objects.update_or_create(
            provider=provider_row,
            service=service,
            country=country,
            defaults={
                "provider_service_code": dto.code,
                "cost_amount": dto.cost,
                "cost_currency": dto.currency,
                "is_available": dto.available,
                "available_count": dto.available_count,
                "supports_sms": dto.supports_sms,
                "supports_voice": dto.supports_voice,
                "ttl_minutes": dto.ttl_minutes,
                "last_synced_at": timezone.now(),
            },
        )
        summary["offerings"] += 1
        if not dto.available:
            summary["unavailable"] += 1

    Provider.objects.filter(pk=provider_row.pk).update(
        last_synced_at=timezone.now(), last_sync_error=""
    )

    # The marketplace response is cached; a sync must invalidate it.
    from apps.catalog import marketplace
    from apps.catalog.views import MARKETPLACE_CACHE_KEY

    cache.delete(MARKETPLACE_CACHE_KEY)
    marketplace.invalidate()

    # A provider price change is a customer price change: write it down.
    from apps.pricing.history import refresh_offering_prices
    from apps.pricing.models import PriceChangeSource

    summary["price_changes"] = refresh_offering_prices(
        source=PriceChangeSource.PROVIDER_COST, reason="Catalogue sync"
    )["changed"]

    logger.info("catalog_synced", extra=summary)
    return summary
