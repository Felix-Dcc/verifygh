from __future__ import annotations

import logging
from collections import defaultdict

from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Country, Service, ServiceCategory
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
    from apps.catalog.marketplace import sellable_offerings
    from apps.funding.services import unfunded_offering_ids

    # Only the marketplace countries - the same rule the purchase enforces.
    offerings = list(sellable_offerings().select_related("provider", "service", "country"))
    # And only what our provider balance can pay for, as far as we know.
    unfunded = unfunded_offering_ids(offerings)
    offerings = [offering for offering in offerings if str(offering.pk) not in unfunded]

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
                "country_count": len(countries),
                "countries": countries,
            }
        )

    used_categories = {entry["category"] for entry in services_payload}
    categories = [
        {"value": str(value), "label": label}
        for value, label in ServiceCategory.choices
        if value in used_categories
    ]

    from apps.catalog.marketplace import marketplace_countries

    countries_payload = CountrySerializer(marketplace_countries(), many=True).data

    return {
        "services": services_payload,
        "categories": categories,
        "countries": countries_payload,
    }


def _without_countries(service: dict) -> dict:
    """A service as the list shows it: everything except the country array.

    That array is the whole weight of the response. With the full OnlineSim
    catalogue the list carried about 15,000 country entries across 2,000
    services - 3.4MB in one unpaginated reply, which on Ghanaian mobile data is
    both slow and genuinely expensive, on every visit to the marketplace.

    The list therefore carries `from_price` and `country_count`, which is what a
    card actually renders, and the countries themselves come from the detail
    endpoint when someone opens one.
    """
    return {key: value for key, value in service.items() if key != "countries"}


def _with_country_preview(service: dict, limit: int = 3) -> dict:
    """A service with just enough countries to show a few flags.

    Used by the landing page, which shows up to three flags per card. Eight
    services times three countries is nothing; eight full country arrays would
    be the same mistake as the list, in miniature.
    """
    available = [entry for entry in service.get("countries", []) if entry["available"]]
    return {**service, "countries": available[:limit]}


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
                                     "country_count": len(matches),
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
                "results": [_without_countries(service) for service in services],
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
        return Response({"results": [_with_country_preview(s) for s in featured]})


class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CountrySerializer
    permission_classes = [AllowAny]
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        from apps.catalog.marketplace import marketplace_country_codes

        return Country.objects.filter(
            is_enabled=True, code__in=marketplace_country_codes()
        ).order_by("display_order", "name")

    def list(self, request, *args, **kwargs):
        from apps.catalog.marketplace import marketplace_countries

        # In the configured order, so the first is the default everywhere.
        return Response(CountrySerializer(marketplace_countries(), many=True).data)


class CatalogHealthView(APIView):
    """Whether the marketplace can currently sell anything.

    The landing page uses this to say "supported services" honestly rather than
    promising a catalogue that is not there.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        from apps.catalog.services import marketplace_readiness

        return Response(marketplace_readiness(), status=status.HTTP_200_OK)


class MarketplaceViewSet(viewsets.ViewSet):
    """The SMS Verifications marketplace.

    Browsing is public; pins need an account. Every price and every stock
    figure is computed here - the client sends a country and a search term and
    renders what comes back.
    """

    permission_classes = [AllowAny]
    lookup_field = "slug"
    lookup_value_regex = "[a-z0-9_.-]+"

    def get_permissions(self):
        from rest_framework.permissions import IsAuthenticated

        if self.action in {"pin", "pins"}:
            return [IsAuthenticated()]
        return super().get_permissions()

    def _country(self, request) -> str:
        from apps.catalog.marketplace import require_marketplace_country

        return require_marketplace_country(request.query_params.get("country"))

    def list(self, request):
        """Server-side search and pagination over one country's services."""
        from apps.catalog import marketplace as mp

        country = self._country(request)
        rows = mp.search(mp.listable(mp.country_rows(country)),
                         request.query_params.get("search", ""),
                         request.query_params.get("category", ""))
        if request.query_params.get("include_unavailable") != "true":
            rows = [row for row in rows if row["availability"] != mp.UNAVAILABLE]
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 50))
        except ValueError:
            page, page_size = 1, 50
        pinned = set(mp.pinned_slugs(request.user))
        result = mp.paginate(rows, page, page_size)
        result["results"] = [mp.public_row(row, pinned) for row in result["results"]]
        result["country"] = country
        return Response(result)

    @action(detail=False, methods=["get"])
    def home(self, request):
        """Everything above the full list: countries, pinned and popular."""
        from apps.catalog import marketplace as mp

        country = self._country(request)
        every_row = mp.country_rows(country)
        rows = mp.listable(every_row)
        by_slug = {row["slug"]: row for row in rows}
        # Pins also see services we cannot pay for right now, badged
        # "temporarily unavailable", so the pin is not silently lost.
        pinnable = {row["slug"]: row for row in every_row}
        pinned = mp.pinned_slugs(request.user)
        pinned_set = set(pinned)
        return Response({
            "country": country,
            "countries": CountrySerializer(mp.marketplace_countries(), many=True).data,
            "voice_available": any(row["supports_voice"] for row in rows),
            "categories": mp.categories(rows),
            # A pinned service stays visible when out of stock here - hiding it
            # would look like the pin was lost. Pins not sold here at all are
            # listed with unavailable_here so the client can say so.
            "pinned": [
                mp.public_row(pinnable[slug], pinned_set) if slug in pinnable
                else {"slug": slug, "pinned": True, "unavailable_here": True,
                      **_service_meta(slug)}
                for slug in pinned
            ],
            "popular": [mp.public_row(by_slug[slug], pinned_set)
                        for slug in mp.popular_slugs(country) if slug in by_slug],
            "total": len([row for row in rows if row["availability"] != mp.UNAVAILABLE]),
        })

    def retrieve(self, request, slug=None):
        """One service in every marketplace country - the purchase screen."""
        from apps.catalog import marketplace as mp

        service = Service.objects.filter(slug=slug, is_enabled=True).first()
        if service is None:
            raise NotFound("We do not offer that service.")
        from apps.catalog import stock

        options = []
        for country in mp.marketplace_countries():
            # Asks the provider at most once per STOCK_CACHE_SECONDS; a change
            # rebuilds the rows read just below.
            offering = stock.preferred_offering(service, country.code)
            live = stock.check(offering) if offering is not None else None
            row = next((r for r in mp.country_rows(country.code) if r["slug"] == slug), None)
            options.append({
                "stock_error": bool(live and live.state == stock.ERROR),
                "code": country.code, "name": country.name, "flag_emoji": country.flag_emoji,
                "dial_code": country.dial_code,
                **({"offered": True, "price": row["price"], "currency": row["currency"],
                    "availability": row["availability"],
                    "available_count": row["available_count"],
                    "temporarily_unavailable": row["temporarily_unavailable"]}
                   if row else {"offered": False, "availability": mp.UNAVAILABLE}),
            })
        return Response({
            "slug": service.slug, "name": service.name, "category": service.category,
            "icon_url": service.icon_url, "accent_color": service.accent_color,
            "description": service.description,
            "maintenance_note": service.maintenance_note if service.is_maintenance else "",
            "pinned": slug in set(mp.pinned_slugs(request.user)),
            "countries": options,
        })

    @action(detail=False, methods=["get"])
    def pins(self, request):
        from apps.catalog.marketplace import pinned_slugs

        return Response({"pinned": pinned_slugs(request.user)})

    @action(detail=True, methods=["post", "delete"])
    def pin(self, request, slug=None):
        from apps.catalog.marketplace import pin, pinned_slugs, unpin

        if request.method == "POST":
            pin(request.user, slug)
        else:
            unpin(request.user, slug)
        return Response({"pinned": pinned_slugs(request.user)})


def _service_meta(slug: str) -> dict:
    service = Service.objects.filter(slug=slug).only(
        "name", "category", "icon_url", "accent_color"
    ).first()
    if service is None:
        return {"name": slug}
    return {"name": service.name, "category": service.category, "icon_url": service.icon_url,
            "accent_color": service.accent_color, "availability": "UNAVAILABLE",
            "available_count": None, "price": None}


class ServiceLogoView(APIView):
    """An uploaded service logo, served from the database.

    Public and heavily cached: the URL carries a version (?v=) that changes
    whenever the logo does, so browsers keep it for a year and never ask again.
    The sandboxing policy means an SVG opened directly in a tab cannot run
    anything, on top of the checks it passed at upload.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    # Static content: a page of logos must not use up a visitor's API budget.
    throttle_classes: list = []

    def get(self, request, slug: str):
        from django.http import HttpResponse

        from apps.catalog.models import ServiceLogo

        logo = (ServiceLogo.objects.filter(service__slug=slug).select_related("service")
                .only("data", "service__logo_content_type").first())
        if logo is None or not logo.data or not logo.service.logo_content_type:
            raise NotFound("No logo.")
        response = HttpResponse(bytes(logo.data), content_type=logo.service.logo_content_type)
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        response["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        response["X-Content-Type-Options"] = "nosniff"
        return response
