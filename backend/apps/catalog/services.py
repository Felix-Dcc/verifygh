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
            category, accent = SERVICE_METADATA.get(slug, (ServiceCategory.OTHER, "#0F766E"))
            service, created = Service.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": dto.name,
                    "category": category,
                    "accent_color": accent,
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
    from apps.catalog.views import MARKETPLACE_CACHE_KEY

    cache.delete(MARKETPLACE_CACHE_KEY)

    logger.info("catalog_synced", extra=summary)
    return summary
