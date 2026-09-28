"""The customer marketplace: what can be bought, where, for how much.

Everything a customer sees is derived here from the synced catalogue and the
pricing engine. Nothing is typed into the frontend, and three things are
deliberately never made up:

* **Countries.** Only MARKETPLACE_COUNTRIES (US and CA today). The list, the
  quote and the purchase all refuse anything else, so a customer editing a
  request cannot buy from a country we have chosen not to sell.
* **Stock.** A count is shown only when the provider reported one and it is
  plausibly a count. OnlineSim answers 9999 for nearly everything, which reads
  as a ceiling, so above AVAILABILITY_EXACT_COUNT_MAX the row just says
  "Available".
* **Popularity.** Staff choose popular services; platform activity (real
  orders, real deliveries, real customers) adds more. No invented figures.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from math import ceil

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.catalog.models import Country, PinnedService, ProviderService, Service, ServiceCategory
from apps.common.errors import ValidationFailed

logger = logging.getLogger("verifygh.catalog")

ROWS_CACHE_SECONDS = 45
POPULAR_CACHE_SECONDS = 600
_ROWS_KEY = "marketplace:rows:v2:{country}"
_POPULAR_KEY = "marketplace:popular:v2:{country}"

AVAILABLE, LIMITED, UNAVAILABLE = "AVAILABLE", "LIMITED", "UNAVAILABLE"


class UnsupportedCountry(ValidationFailed):
    code = "UNSUPPORTED_COUNTRY"
    message = "We only offer numbers for the United States and Canada at the moment."


# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------


def marketplace_country_codes() -> list[str]:
    return [str(code).strip().upper() for code in settings.VERIFYGH["MARKETPLACE_COUNTRIES"]
            if str(code).strip()]


def require_marketplace_country(code: str | None) -> str:
    """Normalise a requested country, or refuse it. Defaults to the first one."""
    allowed = marketplace_country_codes()
    if not code:
        if not allowed:
            raise UnsupportedCountry("No countries are on sale right now.")
        return allowed[0]
    code = str(code).strip().upper()
    if code not in allowed:
        raise UnsupportedCountry()
    return code


def marketplace_countries() -> list[Country]:
    allowed = marketplace_country_codes()
    rows = {c.code: c for c in Country.objects.filter(code__in=allowed, is_enabled=True)}
    # In the configured order: the first is the default tab.
    return [rows[code] for code in allowed if code in rows]


# ---------------------------------------------------------------------------
# Offerings
# ---------------------------------------------------------------------------


def sellable_offerings() -> QuerySet:
    """Every offering a customer could be shown: enabled all the way up, and in
    a marketplace country. In stock or not - availability is a display state."""
    return ProviderService.objects.filter(
        is_enabled=True,
        provider__is_enabled=True,
        service__is_enabled=True,
        country__is_enabled=True,
        country__code__in=marketplace_country_codes(),
    )


def availability(offering: ProviderService, service: Service | None = None) -> dict:
    """What the customer is told about stock. Only what the provider said."""
    service = service or offering.service
    count = offering.available_count
    if service.is_maintenance or not offering.is_available or count == 0:
        state = UNAVAILABLE
    elif count is not None and count <= int(settings.VERIFYGH["AVAILABILITY_LIMITED_THRESHOLD"]):
        state = LIMITED
    else:
        state = AVAILABLE
    shown = count if (count is not None and state != UNAVAILABLE
                      and count <= int(settings.VERIFYGH["AVAILABILITY_EXACT_COUNT_MAX"])) else None
    return {"availability": state, "available_count": shown}


def _row(offering: ProviderService, quote) -> dict:
    service = offering.service
    return {
        "slug": service.slug,
        "name": service.name,
        "category": service.category,
        "icon_url": service.icon_url,
        "accent_color": service.accent_color,
        "country": offering.country.code,
        "price": str(quote.customer_price),
        "currency": quote.currency,
        "supports_sms": offering.supports_sms,
        "supports_voice": offering.supports_voice,
        "maintenance_note": service.maintenance_note if service.is_maintenance else "",
        **availability(offering, service),
        # Searched, never shown.
        "_terms": " ".join([service.name, service.slug, service.aliases]).lower(),
        "_order": (service.display_order, service.name.lower()),
    }


def country_rows(country_code: str) -> list[dict]:
    """Every service sold in one country, priced, one row each. Cached briefly.

    Where several providers offer the same service, the one the purchase would
    actually use is shown: lowest provider priority, then cheapest - the same
    choice `orders.services.resolve_offering` makes.
    """
    from apps.pricing.engine import NoPricingRule, quote_many

    key = _ROWS_KEY.format(country=country_code)
    rows = cache.get(key)
    if rows is not None:
        return rows

    offerings = list(
        sellable_offerings().filter(country__code=country_code)
        .select_related("service", "country", "provider")
        # Uploaded logo bytes are served by their own endpoint, never listed.
        .defer("service__logo_data")
        .order_by("service_id", "-is_available", "provider__priority", "cost_amount")
    )
    try:
        quotes = quote_many(offerings)
    except NoPricingRule:
        logger.error("marketplace_no_pricing_rule")
        return []

    best: dict = {}
    for offering in offerings:
        quote = quotes.get(str(offering.pk))
        if quote is not None and offering.service_id not in best:
            best[offering.service_id] = _row(offering, quote)

    rows = sorted(best.values(), key=lambda row: row["_order"])
    cache.set(key, rows, ROWS_CACHE_SECONDS)
    return rows


def public_row(row: dict, pinned: set[str] | None = None) -> dict:
    data = {k: v for k, v in row.items() if not k.startswith("_")}
    data["pinned"] = bool(pinned and row["slug"] in pinned)
    return data


def search(rows: list[dict], query: str = "", category: str = "") -> list[dict]:
    """Case-insensitive match on name, slug and aliases ("gmail" finds Google).

    Exact and prefix matches first, so typing "x" leads with X rather than
    every name that happens to contain the letter.
    """
    if category:
        rows = [row for row in rows if row["category"] == category.upper()]
    needle = " ".join(str(query or "").lower().split())
    if not needle:
        return rows

    def rank(row) -> int | None:
        name = row["name"].lower()
        words = row["_terms"].replace(",", " ").replace("|", " ").replace("(", " ").split()
        if needle == name or needle in words:
            return 0
        if name.startswith(needle) or any(word.startswith(needle) for word in words):
            return 1
        if needle in row["_terms"]:
            return 2
        return None

    ranked = [(rank(row), row) for row in rows]
    return [row for score, row in sorted(
        ((s, r) for s, r in ranked if s is not None), key=lambda pair: pair[0])]


def paginate(rows: list, page: int, page_size: int) -> dict:
    page_size = max(1, min(100, page_size))
    pages = max(1, ceil(len(rows) / page_size))
    page = max(1, min(page, pages))
    start = (page - 1) * page_size
    return {"results": rows[start:start + page_size], "count": len(rows), "page": page,
            "pages": pages, "has_next": page < pages}


# ---------------------------------------------------------------------------
# Popular and pinned
# ---------------------------------------------------------------------------


def popular_slugs(country_code: str) -> list[str]:
    """Staff picks first, then services with real recent activity here.

    Activity counts only what happened on this platform in the last 30 days:
    codes delivered weigh most, then distinct customers, then purchases. A
    service with no activity and no staff pick is simply not popular.
    """
    key = _POPULAR_KEY.format(country=country_code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    from apps.orders.models import Order

    limit = int(settings.VERIFYGH["POPULAR_SERVICES_LIMIT"])
    sold_here = {row["slug"] for row in country_rows(country_code)
                 if row["availability"] != UNAVAILABLE}

    picks = [
        slug for slug in Service.objects.filter(is_popular=True, is_enabled=True)
        .order_by("popular_rank", "name").values_list("slug", flat=True)
        if slug in sold_here
    ]
    activity = (
        Order.objects.filter(country__code=country_code,
                             created_at__gte=timezone.now() - timedelta(days=30))
        .values("service__slug")
        .annotate(
            purchases=Count("id"),
            delivered=Count("id", filter=Q(code_received_at__isnull=False)),
            customers=Count("user", distinct=True),
        )
    )
    scored = sorted(
        ((row["delivered"] * 3 + row["customers"] * 2 + row["purchases"], row["service__slug"])
         for row in activity if row["service__slug"] in sold_here),
        reverse=True,
    )
    slugs = picks + [slug for score, slug in scored if score > 0 and slug not in picks]
    slugs = slugs[:limit]
    cache.set(key, slugs, POPULAR_CACHE_SECONDS)
    return slugs


def pinned_slugs(user) -> list[str]:
    if not getattr(user, "is_authenticated", False):
        return []
    return list(
        PinnedService.objects.filter(user=user).order_by("created_at")
        .values_list("service__slug", flat=True)
    )


def pin(user, slug: str) -> None:
    from apps.common.errors import NotFound

    service = Service.objects.filter(slug=slug, is_enabled=True).first()
    if service is None:
        raise NotFound("We do not offer that service.")
    # get_or_create plus the unique constraint: a double tap pins once.
    PinnedService.objects.get_or_create(user=user, service=service)


def unpin(user, slug: str) -> None:
    PinnedService.objects.filter(user=user, service__slug=slug).delete()


def categories(rows: list[dict]) -> list[dict]:
    used = {row["category"] for row in rows}
    return [{"value": str(value), "label": label}
            for value, label in ServiceCategory.choices if value in used]


def invalidate() -> None:
    for code in marketplace_country_codes():
        cache.delete(_ROWS_KEY.format(country=code))
        cache.delete(_POPULAR_KEY.format(country=code))
