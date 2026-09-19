from __future__ import annotations

import logging
from collections import defaultdict

from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Country, ProviderService, Service, ServiceCategory
from apps.catalog.serializers import CountrySerializer
from apps.common.errors import NotFound
from apps.pricing.engine import NoPricingRule, quote_many

logger = logging.getLogger("verifygh.catalog")

#: The marketplace is read-heavy and changes slowly, so it is cached briefly.
#: Short enough that disabling a service takes effect almost immediately.
MARKETPLACE_CACHE_SECONDS = 45
MARKETPLACE_CACHE_KEY = "catalog:marketplace:v1"


def _build_marketplace() -> dict:
    """Assemble the whole catalogue with server-computed prices.

    Nothing here is hardcoded: services, countries, availability and cost come
    from the synced catalog, and every price goes through the pricing engine.
    """
    offerings = list(
        ProviderService.objects.select_related("provider", "service", "country").filter(
            is_enabled=True,
            provider__is_enabled=True,
            service__is_enabled=True,
            country__is_enabled=True,
        )
    )

    try:
        quotes = quote_many(offerings)
    except NoPricingRule:
        logger.error("marketplace_no_pricing_rule")
        return {"services": [], "categories": [], "countries": [], "unavailable_reason":
                "Pricing is being configured."}

    # Keep the cheapest offering per (service, country) - that is what the user
    # is shown, and which upstream provider fulfils it is our concern, not theirs.
    best: dict[tuple, tuple] = {}
    for offering in offerings:
        quote = quotes.get(str(offering.id))
        if quote is None:
            continue
        key = (offering.service_id, offering.country_id)
        current = best.get(key)
        if current is None or quote.customer_price < current[1].customer_price:
            best[key] = (offering, quote)

    by_service: dict[str, list] = defaultdict(list)
    for (service_id, _country_id), (offering, quote) in best.items():
        by_service[service_id].append((offering, quote))

    services_payload = []
    for service in Service.objects.filter(is_enabled=True).order_by("display_order", "name"):
        entries = by_service.get(service.id, [])
        if not entries:
            continue

        countries = []
        for offering, quote in sorted(
            entries, key=lambda pair: (pair[0].country.display_order, pair[0].country.name)
        ):
            countries.append(
                {
                    "code": offering.country.code,
                    "name": offering.country.name,
                    "flag_emoji": offering.country.flag_emoji,
                    "dial_code": offering.country.dial_code,
                    "price": str(quote.customer_price),
                    "currency": quote.currency,
                    "available": offering.is_available and service.is_available,
                    "available_count": offering.available_count,
                    "supports_sms": offering.supports_sms,
                    "supports_voice": offering.supports_voice,
                    "ttl_minutes": offering.ttl_minutes,
                }
            )

        available_prices = [
            entry["price"] for entry in countries if entry["available"]
        ]
        services_payload.append(
            {
                "slug": service.slug,
                "name": service.name,
                "category": service.category,
                "icon_url": service.icon_url,
                "accent_color": service.accent_color,
                "description": service.description,
                "supports_sms": service.supports_sms,
                "supports_voice": service.supports_voice,
                "is_maintenance": service.is_maintenance,
                "maintenance_note": service.maintenance_note,
                "available": service.is_available and bool(available_prices),
                "from_price": min(available_prices, key=lambda value: float(value))
                if available_prices
                else None,
                "currency": "GHS",
                "countries": countries,
            }
        )

    used_categories = {entry["category"] for entry in services_payload}
    categories = [
        {"value": str(value), "label": label}
        for value, label in ServiceCategory.choices
        if value in used_categories
    ]

    countries_payload = CountrySerializer(
        Country.objects.filter(is_enabled=True).order_by("display_order", "name"), many=True
    ).data

    return {
        "services": services_payload,
        "categories": categories,
        "countries": countries_payload,
    }


class ServiceViewSet(viewsets.ViewSet):
    """Public marketplace.

    Browsing does not require an account - the landing page shows real,
    live availability rather than a static list.
    """

    permission_classes = [AllowAny]

    def list(self, request):
        payload = cache.get(MARKETPLACE_CACHE_KEY)
        if payload is None:
            payload = _build_marketplace()
            cache.set(MARKETPLACE_CACHE_KEY, payload, MARKETPLACE_CACHE_SECONDS)

        services = payload["services"]

        category = request.query_params.get("category")
        if category:
            services = [
                service for service in services if service["category"] == category.upper()
            ]

        country = request.query_params.get("country")
        if country:
            country = country.upper()
            filtered = []
            for service in services:
                matches = [
                    entry for entry in service["countries"] if entry["code"] == country
                ]
                if matches:
                    filtered.append({**service, "countries": matches,
                                     "from_price": matches[0]["price"]})
            services = filtered

        search = request.query_params.get("search")
        if search:
            needle = search.lower().strip()
            services = [
                service
                for service in services
                if needle in service["name"].lower() or needle in service["slug"]
            ]

        if request.query_params.get("available") == "true":
            services = [service for service in services if service["available"]]

        return Response(
            {
                "results": services,
                "categories": payload["categories"],
                "countries": payload["countries"],
                "count": len(services),
            }
        )

    def retrieve(self, request, pk: str = None):
        payload = cache.get(MARKETPLACE_CACHE_KEY)
        if payload is None:
            payload = _build_marketplace()
            cache.set(MARKETPLACE_CACHE_KEY, payload, MARKETPLACE_CACHE_SECONDS)

        for service in payload["services"]:
            if service["slug"] == pk:
                return Response(service)
        raise NotFound("We do not offer that service.")

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """A short list for the landing page - real services, real prices."""
        payload = cache.get(MARKETPLACE_CACHE_KEY)
        if payload is None:
            payload = _build_marketplace()
            cache.set(MARKETPLACE_CACHE_KEY, payload, MARKETPLACE_CACHE_SECONDS)
        featured = [service for service in payload["services"] if service["available"]][:8]
        return Response({"results": featured})


class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CountrySerializer
    permission_classes = [AllowAny]
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        return Country.objects.filter(is_enabled=True).order_by("display_order", "name")


class CatalogHealthView(APIView):
    """Whether the marketplace can currently sell anything.

    The landing page uses this to say "supported services" honestly rather than
    promising a catalogue that is not there.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        from apps.pricing.rates import latest_rate_row
        from apps.verification.registry import get_default_provider_row

        provider_row = get_default_provider_row()
        rate = latest_rate_row()
        purchasable = ProviderService.objects.filter(
            is_enabled=True, is_available=True, provider__is_enabled=True,
            service__is_enabled=True, country__is_enabled=True,
        ).count()

        ready = bool(provider_row and rate and purchasable)
        return Response(
            {
                "ready": ready,
                "provider_configured": provider_row is not None,
                "exchange_rate_configured": rate is not None,
                "purchasable_offerings": purchasable,
            },
            status=status.HTTP_200_OK,
        )
