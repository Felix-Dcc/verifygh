"""Live stock: what the provider says it can supply, right now.

The catalogue sync cannot keep stock current: TextVerified's service list
carries prices, not stock. So stock is asked for separately, through the
adapter's documented `get_availability` (TextVerified: POST
/api/pub/v2/inventory/verifications), and kept on the ProviderService row the
marketplace already reads.

* A display check is cached for STOCK_CACHE_SECONDS, so a busy service costs
  one provider call per window, not one per visitor.
* The check just before a purchase is always fresh (max_age=0).
* A provider error or timeout is ERROR, never OUT_OF_STOCK: the last known
  stock stands, and the customer is told the provider is not answering.
* A purchase the provider refuses as out of stock (8 Oct 2026: WhatsApp was
  refused while the inventory endpoint still reported stock) holds the
  offering out of stock for a while, doubling on repeat refusals. Until the
  hold ends the inventory figure is not believed; after it, `recheck` asks
  again and a returning stock shows as available by itself.

Call budget. Every check is one provider call, and the provider's rate limit
is shared with customers' orders, so:

* concurrent visitors share one display check (single flight): the rest read
  the last known stock instead of calling too;
* the background recheck runs one at a time, at most RECHECK_LIMIT offerings
  per run, services customers buy first, paced by apps/verification/pacing.py,
  and it stops at the first provider error;
* an offering that stays out of stock is rechecked less and less often (2, 4,
  8 ... up to 30 minutes); opening its purchase screen still checks it at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.catalog.models import ProviderService
from apps.common.errors import ProviderError, ServiceUnavailable

logger = logging.getLogger("verifygh.catalog.stock")

STOCK_CACHE_SECONDS = 45
#: An unanswered display check is not repeated for this long.
ERROR_CACHE_SECONDS = 15
#: The first hold after a refused purchase; doubles per repeat, up to the cap.
REFUSAL_HOLD_SECONDS = 600
REFUSAL_HOLD_CAP_SECONDS = 3600
#: Repeat refusals are counted within this window.
REFUSAL_MEMORY_SECONDS = 24 * 3600
#: The background recheck: offerings per run, and the per-offering backoff.
RECHECK_LIMIT = 20
RECHECK_TIME_BUDGET_SECONDS = 30
RECHECK_FIRST_SECONDS = 120
RECHECK_CAP_SECONDS = 1800
#: A display check in flight; others read the last known stock meanwhile.
INFLIGHT_SECONDS = 10

IN_STOCK, OUT_OF_STOCK, ERROR = "IN_STOCK", "OUT_OF_STOCK", "ERROR"

_CHECK_KEY = "stock:check:{pk}"
_HOLD_KEY = "stock:hold:{pk}"
_REFUSALS_KEY = "stock:refusals:{pk}"
_INFLIGHT_KEY = "stock:inflight:{pk}"
_NEXT_KEY = "stock:next:{pk}"
_STEP_KEY = "stock:step:{pk}"
_RECHECK_LOCK = "stock:recheck:lock"


@dataclass(frozen=True)
class StockCheck:
    state: str
    count: int | None = None

    @property
    def in_stock(self) -> bool:
        return self.state == IN_STOCK


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_add(key: str, value, seconds: int) -> bool:
    try:
        return bool(cache.add(key, value, seconds))
    except Exception:
        return True


def _cache_delete(*keys: str) -> None:
    try:
        cache.delete_many(list(keys))
    except Exception:
        pass


def _cache_set(key: str, value, seconds: int) -> None:
    try:
        cache.set(key, value, seconds)
    except Exception:
        # Without the cache every check asks the provider; still correct.
        logger.warning("stock_cache_unavailable")


def is_held(offering: ProviderService) -> bool:
    return bool(_cache_get(_HOLD_KEY.format(pk=offering.pk)))


def _store(offering: ProviderService, available: bool, count: int | None) -> None:
    """Write the answer to the row the marketplace lists from."""
    changed = offering.is_available != available
    if changed or offering.available_count != count:
        ProviderService.objects.filter(pk=offering.pk).update(
            is_available=available, available_count=count)
        offering.is_available, offering.available_count = available, count
    if changed:
        from apps.catalog import marketplace

        marketplace.invalidate()
        logger.info("stock_changed", extra={
            "offering": str(offering.pk), "service": offering.service.slug,
            "country": offering.country.code, "available": available})


def check(offering: ProviderService, *, max_age: int = STOCK_CACHE_SECONDS) -> StockCheck:
    """Can the provider supply this offering now? Cached for display only."""
    if not settings.VERIFYGH.get("CHECK_LIVE_AVAILABILITY", True):
        return StockCheck(IN_STOCK if offering.is_available else OUT_OF_STOCK,
                          offering.available_count)
    if is_held(offering):
        return StockCheck(OUT_OF_STOCK, 0)

    key = _CHECK_KEY.format(pk=offering.pk)
    if max_age > 0:
        cached = _cache_get(key)
        if cached is not None:
            return StockCheck(*cached)
        if not _cache_add(_INFLIGHT_KEY.format(pk=offering.pk), 1, INFLIGHT_SECONDS):
            # Someone else is asking right now: show what we last knew.
            return StockCheck(IN_STOCK if offering.is_available else OUT_OF_STOCK,
                              offering.available_count)

    from apps.verification.registry import get_provider

    try:
        live = get_provider(offering.provider.adapter_key).get_availability(
            offering.provider_service_code or offering.service.slug, offering.country.code)
    except (ProviderError, ServiceUnavailable):
        # Not an answer about stock. What we last knew stands.
        logger.warning("stock_check_failed", extra={
            "offering": str(offering.pk), "service": offering.service.slug})
        _cache_set(key, (ERROR, None), ERROR_CACHE_SECONDS)
        _cache_delete(_INFLIGHT_KEY.format(pk=offering.pk))
        return StockCheck(ERROR)

    _store(offering, live.available, live.count)
    result = StockCheck(IN_STOCK if live.available else OUT_OF_STOCK, live.count)
    _cache_set(key, (result.state, result.count), STOCK_CACHE_SECONDS)
    _cache_delete(_INFLIGHT_KEY.format(pk=offering.pk))
    if result.in_stock:
        # Back in stock: the next time it runs out, rechecks start quick again.
        _cache_delete(_NEXT_KEY.format(pk=offering.pk), _STEP_KEY.format(pk=offering.pk))
    return result


def note_refused(offering: ProviderService) -> None:
    """The provider refused a purchase as out of stock: believe the refusal."""
    refusals_key = _REFUSALS_KEY.format(pk=offering.pk)
    refusals = int(_cache_get(refusals_key) or 0) + 1
    _cache_set(refusals_key, refusals, REFUSAL_MEMORY_SECONDS)
    hold = min(REFUSAL_HOLD_SECONDS * 2 ** (refusals - 1), REFUSAL_HOLD_CAP_SECONDS)
    _cache_set(_HOLD_KEY.format(pk=offering.pk), 1, hold)
    _cache_set(_CHECK_KEY.format(pk=offering.pk), (OUT_OF_STOCK, 0), STOCK_CACHE_SECONDS)
    _store(offering, False, 0)
    logger.warning("stock_purchase_refused", extra={
        "offering": str(offering.pk), "service": offering.service.slug,
        "country": offering.country.code, "hold_seconds": hold, "refusals": refusals})


def preferred_offering(service, country_code: str) -> ProviderService | None:
    """The offering the marketplace lists for a service here, in stock or not."""
    from apps.catalog.marketplace import sellable_offerings

    return (sellable_offerings().filter(service=service, country__code=country_code)
            .select_related("provider", "service", "country")
            .order_by("provider__priority", "cost_amount").first())


def _due(offering: ProviderService) -> bool:
    return _cache_get(_NEXT_KEY.format(pk=offering.pk)) is None


def _back_off(offering: ProviderService) -> None:
    """Still out of stock: ask about this one less often."""
    step = int(_cache_get(_STEP_KEY.format(pk=offering.pk)) or 0)
    wait = min(RECHECK_FIRST_SECONDS * 2 ** step, RECHECK_CAP_SECONDS)
    _cache_set(_NEXT_KEY.format(pk=offering.pk), 1, wait)
    _cache_set(_STEP_KEY.format(pk=offering.pk), step + 1, REFUSAL_MEMORY_SECONDS)


def recheck_out_of_stock(limit: int = RECHECK_LIMIT) -> dict:
    """Ask again about offerings shown out of stock, so returning stock shows.

    Cheap by construction: one run at a time, only offerings that are due,
    the services customers buy first, paced, and it gives up for this run at
    the first provider error - the next run is two minutes away.
    """
    import time

    from apps.catalog.marketplace import sellable_offerings
    from apps.catalog.services import priority_service_codes
    from apps.verification import pacing

    if not settings.VERIFYGH.get("CHECK_LIVE_AVAILABILITY", True):
        return {"asked": 0, "restored": 0, "skipped": "disabled"}
    if not _cache_add(_RECHECK_LOCK, 1, RECHECK_TIME_BUDGET_SECONDS + 30):
        return {"asked": 0, "restored": 0, "skipped": "running"}
    try:
        waiting = [o for o in sellable_offerings().filter(is_available=False)
                   .select_related("provider", "service", "country")
                   if not is_held(o) and _due(o)]
        if not waiting:
            return {"asked": 0, "restored": 0}
        rank = {slug: i for i, slug in enumerate(priority_service_codes())}
        waiting.sort(key=lambda o: (rank.get(o.service.slug, len(rank)), o.service.slug))

        deadline = time.monotonic() + RECHECK_TIME_BUDGET_SECONDS
        asked = restored = 0
        stopped = ""
        for offering in waiting[:limit]:
            adapter = offering.provider.adapter_key
            if not pacing.wait_turn(adapter, deadline):
                stopped = "time_budget"
                break
            asked += 1
            result = check(offering, max_age=0)
            if result.state == ERROR:
                stopped = "provider_error"
                break
            pacing.note_ok(adapter)
            if result.in_stock:
                restored += 1
            else:
                _back_off(offering)
        logger.info("stock_rechecked", extra={
            "waiting": len(waiting), "asked": asked, "restored": restored,
            "stopped": stopped or "complete"})
        return {"asked": asked, "restored": restored}
    finally:
        _cache_delete(_RECHECK_LOCK)
