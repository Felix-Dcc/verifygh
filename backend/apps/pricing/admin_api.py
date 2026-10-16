"""Admin > Pricing: see and control provider cost -> FX -> markup -> price.

Reading needs PRICING_VIEW; changing anything needs PRICING_MANAGE; a price
below cost additionally needs PRICING_LOSS_OVERRIDE. Every change requires a
reason and is written to the AdminAction log (see apps/pricing/services.py).

Provider costs shown here are exactly what the provider integration reported
(or what staff typed in, labelled as such). Nothing is filled in: an offering
whose cost is unknown shows as "Not synced" and is not sold.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.audit.models import AdminAction
from apps.catalog.models import ProviderService
from apps.common.errors import NotFound
from apps.common.money import quantize
from apps.pricing import services
from apps.pricing.engine import NoPricingRule, pricing_fx, quote_many, resolve_rule
from apps.pricing.models import (
    FXMode,
    PriceOverride,
    PricingFXRate,
    PricingPolicy,
    ProviderCostChange,
)
from apps.pricing.rates import latest_rate_row

PRICING_AUDIT_ACTIONS = Q(action__startswith="PRICING_") | Q(action="EXCHANGE_RATE_SET")


def _offerings(params):
    queryset = services.listed_offerings()
    if params.get("provider"):
        queryset = [o for o in queryset if o.provider.adapter_key == params["provider"]]
    if params.get("country"):
        queryset = [o for o in queryset if o.country.code == params["country"].upper()]
    search = (params.get("search") or "").strip().lower()
    if search:
        queryset = [o for o in queryset
                    if search in o.service.name.lower() or search in o.service.slug
                    or search in (o.service.aliases or "").lower()]
    return queryset


def _plain_number(value) -> str:
    """25.00 -> "25", 12.50 -> "12.5": for labels, not for arithmetic."""
    text = f"{Decimal(str(value)).normalize():f}"
    return text


def _markup_label(applied: dict) -> str:
    kind = applied.get("markup_type")
    if kind == "FIXED":
        return f"+ GHS {applied['markup_fixed']}"
    if kind == "HYBRID":
        return f"{_plain_number(applied['markup_percent'])}% + GHS {applied['markup_fixed']}"
    return f"{_plain_number(applied.get('markup_percent'))}%"


def row(offering: ProviderService, published, recommended) -> dict:
    """One line of the pricing table. `published` / `recommended` are quotes or None."""
    quote = published or recommended
    status = "ACTIVE"
    if offering.cost_amount <= 0:
        status = "NOT_SYNCED"
    elif published is None:
        status = "NOT_SOLD"
    elif not offering.is_enabled:
        status = "INACTIVE"
    elif not offering.is_available:
        status = "OUT_OF_STOCK"
    data = {
        "id": str(offering.pk),
        "service": {"slug": offering.service.slug, "name": offering.service.name,
                    "icon_url": offering.service.icon_url},
        "country": {"code": offering.country.code, "name": offering.country.name,
                    "flag": offering.country.flag_emoji},
        "provider": {"key": offering.provider.adapter_key, "name": offering.provider.name,
                     # The mock provider's prices are demo data - label them.
                     "demo": offering.provider.adapter_key == "mock"},
        "provider_cost": str(offering.cost_amount) if offering.cost_amount > 0 else None,
        "currency": offering.cost_currency,
        "cost_source": offering.cost_source,
        "status": status,
        "is_enabled": offering.is_enabled,
        "is_available": offering.is_available,
        "price_review_pending": offering.price_review_pending,
    }
    if quote is not None:
        data.update(
            fx_rate=str(quote.exchange_rate),
            fx_mode=quote.fx_mode,
            ghs_cost=str(quote.base_cost),
            markup=_markup_label(quote.applied),
            markup_type=quote.applied.get("markup_type"),
            markup_percent_effective=str(quote.markup_percent_effective),
            calculated_price=str(quote.calculated_price),
            override_price=str(quote.override_price) if quote.override_price is not None else None,
            recommended_price=str((recommended or quote).recommended_price),
            customer_price=str(quote.customer_price) if published else None,
            gross_profit=str(quote.gross_profit),
            gross_margin_percent=str(quote.gross_margin_percent),
            below_minimum_margin=quote.below_minimum_margin,
            is_loss=quote.is_loss,
            rule=quote.pricing_rule_name,
        )
    return data


def _quotes(offerings):
    try:
        return quote_many(offerings, published=True), quote_many(offerings, published=False)
    except NoPricingRule:
        return {}, {}


class PricingSummaryView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request):
        offerings = services.listed_offerings()
        published, recommended = _quotes(offerings)
        active = [o for o in offerings
                  if str(o.pk) in published and o.is_enabled and o.is_available]
        quotes = [published[str(o.pk)] for o in active]

        def average(values):
            values = list(values)
            return str(quantize(sum(values, Decimal("0")) / len(values))) if values else None

        policy = PricingPolicy.get()
        fx = []
        for currency in sorted({o.cost_currency for o in offerings} | {"USD"}):
            try:
                rate = pricing_fx(currency)
                fx.append({"currency": currency, "pricing_rate": str(rate.rate), "mode": rate.mode,
                           "market_rate": str(rate.market_rate) if rate.market_rate else None,
                           "adjustment_percent": str(rate.adjustment_percent)})
            except Exception as exc:  # shown, not hidden: pricing is off for it
                fx.append({"currency": currency, "error": str(getattr(exc, "message", exc))})
        return Response({
            "total_services": len({o.service_id for o in offerings}),
            "total_offerings": len(offerings),
            "active_offerings": len(active),
            "average_markup_percent": average(q.markup_percent_effective for q in quotes),
            "average_gross_margin_percent": average(q.gross_margin_percent for q in quotes),
            "below_minimum_margin": sum(1 for q in quotes if q.below_minimum_margin),
            "not_sold": sum(1 for o in offerings if str(o.pk) not in published),
            "not_synced": sum(1 for o in offerings if o.cost_amount <= 0),
            "pending_review": sum(1 for o in offerings if o.price_review_pending),
            "active_overrides": PriceOverride.objects.filter(
                is_active=True, offering__in=offerings).count(),
            "fx": fx,
            "policy": _policy(policy),
            "providers": sorted(
                ({"key": key, "name": name, "demo": key == "mock"}
                 for key, name in {(o.provider.adapter_key, o.provider.name) for o in offerings}),
                key=lambda p: p["name"],
            ),
        })


def _policy(policy: PricingPolicy) -> dict:
    return {"minimum_margin_percent": str(policy.minimum_margin_percent),
            "enforce_minimum_margin": policy.enforce_minimum_margin,
            "auto_publish_prices": policy.auto_publish_prices,
            "updated_at": policy.updated_at}


class PricingOfferingViewSet(AdminBase, viewsets.ViewSet):
    required_permission = AdminPermission.PRICING_VIEW

    def list(self, request):
        params = request.query_params
        offerings = _offerings(params)
        published, recommended = _quotes(offerings)
        rows = [row(o, published.get(str(o.pk)), recommended.get(str(o.pk))) for o in offerings]

        status = params.get("status")
        if status == "pending":
            rows = [r for r in rows if r["price_review_pending"]]
        elif status == "override":
            rows = [r for r in rows if r.get("override_price")]
        elif status == "below_minimum":
            rows = [r for r in rows if r.get("below_minimum_margin")]
        elif status:
            rows = [r for r in rows if r["status"] == status.upper()]
        if params.get("active") in ("true", "false"):
            wanted = params["active"] == "true"
            rows = [r for r in rows if (r["status"] == "ACTIVE") == wanted]
        for field, low, high in (("gross_margin_percent", "margin_min", "margin_max"),
                                 ("markup_percent_effective", "markup_min", "markup_max")):
            if params.get(low):
                rows = [r for r in rows if r.get(field) is not None
                        and Decimal(r[field]) >= Decimal(params[low])]
            if params.get(high):
                rows = [r for r in rows if r.get(field) is not None
                        and Decimal(r[field]) <= Decimal(params[high])]

        ordering = params.get("ordering", "service")
        keyed = {
            "service": lambda r: (r["service"]["name"].lower(), r["country"]["code"]),
            "margin": lambda r: Decimal(r.get("gross_margin_percent") or "-1000"),
            "-margin": lambda r: -Decimal(r.get("gross_margin_percent") or "-1000"),
            "price": lambda r: Decimal(
                r.get("customer_price") or r.get("recommended_price") or "0"),
            "-price": lambda r: -Decimal(
                r.get("customer_price") or r.get("recommended_price") or "0"),
            "cost": lambda r: Decimal(r.get("provider_cost") or "0"),
            "-cost": lambda r: -Decimal(r.get("provider_cost") or "0"),
        }
        rows.sort(key=keyed.get(ordering, keyed["service"]))

        page = max(1, int(params.get("page", 1) or 1))
        size = max(1, min(200, int(params.get("page_size", 50) or 50)))
        start = (page - 1) * size
        pages = max(1, -(-len(rows) // size))
        return Response({"results": rows[start:start + size],
                         "pagination": {"count": len(rows), "page": page, "pages": pages,
                                        "has_next": page < pages, "has_previous": page > 1}})

    def _offering(self, pk) -> ProviderService:
        offering = ProviderService.objects.select_related("service", "country", "provider").filter(
            pk=pk).first()
        if offering is None:
            raise NotFound("We could not find that offering.")
        return offering

    def retrieve(self, request, pk=None):
        offering = self._offering(pk)
        published, recommended = _quotes([offering])
        key = str(pk)
        rule = None
        try:
            resolved = resolve_rule(offering.service_id, offering.country_id, offering.provider_id)
            rule = {"id": str(resolved.pk), "name": resolved.name,
                    "scope": {"service": offering.service.slug if resolved.service_id else None,
                              "country": offering.country.code if resolved.country_id else None,
                              "provider": (offering.provider.adapter_key
                                           if resolved.provider_id else None)},
                    "markup_type": resolved.markup_type,
                    "markup_percent": str(resolved.markup_percent),
                    "markup_fixed": str(resolved.markup_fixed)}
        except NoPricingRule:
            pass

        comparison = []
        for other in ProviderService.objects.filter(
                service=offering.service, country=offering.country).select_related("provider"):
            entry = {"provider": other.provider.name, "provider_key": other.provider.adapter_key,
                     "cost": str(other.cost_amount) if other.cost_amount > 0 else None,
                     "currency": other.cost_currency, "available": other.is_available,
                     "enabled": other.is_enabled and other.provider.is_enabled,
                     "priority": other.provider.priority, "this": other.pk == offering.pk}
            try:
                entry["ghs_cost"] = str(quantize(
                    other.cost_amount * pricing_fx(other.cost_currency).rate))
            except Exception:
                entry["ghs_cost"] = None
            comparison.append(entry)
        costs = [Decimal(c["ghs_cost"]) for c in comparison
                 if c["ghs_cost"] and c["available"] and c["enabled"]]

        return Response({
            "row": row(offering, published.get(key), recommended.get(key)),
            "published": published[key].as_dict() if key in published else None,
            "recommended": recommended[key].as_dict() if key in recommended else None,
            "rule": rule,
            "cost_editable": offering.cost_source != "PROVIDER_API",
            "overrides": [
                {"price": str(o.price), "reason": o.reason, "allow_loss": o.allow_loss,
                 "is_active": o.is_active, "created_by": getattr(o.created_by, "email", None),
                 "created_at": o.created_at, "ended_by": getattr(o.ended_by, "email", None),
                 "ended_at": o.ended_at, "end_reason": o.end_reason}
                for o in offering.price_overrides.select_related("created_by", "ended_by")[:10]
            ],
            "cost_history": [
                {"old": str(c.old_cost) if c.old_cost is not None else None, "new": str(c.new_cost),
                 "currency": c.currency, "source": c.source, "sync_method": c.sync_method,
                 "by": getattr(c.changed_by, "email", None), "reason": c.reason,
                 "at": c.created_at}
                for c in offering.cost_changes.select_related("changed_by")[:15]
            ],
            "price_history": [
                {"old": str(c.old_price) if c.old_price is not None else None,
                 "new": str(c.new_price), "source": c.get_source_display(),
                 "by": getattr(c.changed_by, "email", None), "reason": c.reason, "at": c.created_at}
                for c in offering.price_changes.select_related("changed_by")[:15]
            ],
            "provider_comparison": {
                "providers": comparison,
                "lowest_available_ghs_cost": str(min(costs)) if costs else None,
                "routing": "Purchases use the lowest provider priority first, then the lowest "
                           "cost among providers of equal priority, among those in stock.",
            },
        })

    # -- changes -------------------------------------------------------------

    def _manage(self, request, permission=AdminPermission.PRICING_MANAGE):
        self.required_permission = permission
        self.check_permissions(request)

    @action(detail=True, methods=["post", "delete"])
    def override(self, request, pk=None):
        self._manage(request)
        offering = self._offering(pk)
        if request.method == "DELETE":
            services.remove_override(offering, reason=request.data.get("reason"),
                                     actor=request.user, request=request)
        else:
            services.set_override(offering, price=request.data.get("price"),
                                  reason=request.data.get("reason"),
                                  allow_loss=bool(request.data.get("allow_loss")),
                                  actor=request.user, request=request)
        return self.retrieve(request, pk)

    @action(detail=True, methods=["post"])
    def cost(self, request, pk=None):
        self._manage(request)
        services.set_manual_cost(self._offering(pk), cost=request.data.get("cost"),
                                 currency=request.data.get("currency", ""),
                                 reason=request.data.get("reason"), actor=request.user,
                                 request=request)
        return self.retrieve(request, pk)

    @action(detail=True, methods=["post"])
    def markup(self, request, pk=None):
        """Set the markup for this offering's service in this country."""
        self._manage(request)
        offering = self._offering(pk)
        scope = {"service": offering.service.slug, "country": offering.country.code}
        if request.data.get("scope") == "service":
            scope = {"service": offering.service.slug}
        services.apply_markup(scope=scope, data=request.data, reason=request.data.get("reason"),
                              actor=request.user, request=request)
        return self.retrieve(request, pk)


class PricingPreviewView(AdminBase, APIView):
    """Price one offering under proposed inputs. Read-only."""

    required_permission = AdminPermission.PRICING_VIEW

    def post(self, request):
        offering = ProviderService.objects.select_related("service", "country", "provider").filter(
            pk=request.data.get("offering_id")).first()
        if offering is None:
            raise NotFound("We could not find that offering.")
        return Response(services.preview(offering, request.data))


class PricingFXView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request):
        configs = {c.base_currency: c for c in PricingFXRate.objects.select_related("updated_by")}
        currencies = sorted(set(configs) | {"USD"})
        out = []
        for currency in currencies:
            config = configs.get(currency)
            market = latest_rate_row(currency, "GHS")
            try:
                effective = pricing_fx(currency)
                effective_rate, error = str(effective.rate), ""
            except Exception as exc:
                effective_rate, error = None, str(getattr(exc, "message", exc))
            out.append({
                "currency": currency,
                "mode": config.mode if config else "MARKET",
                "manual_rate": str(config.manual_rate) if config and config.manual_rate else None,
                "adjustment_percent": str(config.adjustment_percent) if config else "0.00",
                "effective_rate": effective_rate,
                "error": error,
                "market_rate": str(market.rate) if market else None,
                "market_rate_source": market.source if market else None,
                "market_rate_at": market.fetched_at if market else None,
                "updated_by": getattr(getattr(config, "updated_by", None), "email", None),
                "updated_at": config.updated_at if config else None,
            })
        return Response({"rates": out, "modes": FXMode.values})

    def put(self, request):
        self.required_permission = AdminPermission.PRICING_MANAGE
        self.check_permissions(request)
        services.set_fx(currency=request.data.get("currency", "USD"), mode=request.data.get("mode"),
                        manual_rate=request.data.get("manual_rate"),
                        adjustment=request.data.get("adjustment_percent"),
                        reason=request.data.get("reason"), actor=request.user, request=request)
        return self.get(request)


class PricingFXPreviewView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def post(self, request):
        return Response(services.preview_fx(
            currency=request.data.get("currency", "USD"), mode=request.data.get("mode"),
            manual_rate=request.data.get("manual_rate"),
            adjustment=request.data.get("adjustment_percent")))


class PricingPolicyView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request):
        return Response(_policy(PricingPolicy.get()))

    def put(self, request):
        self.required_permission = AdminPermission.PRICING_MANAGE
        self.check_permissions(request)
        policy = services.set_policy(data=request.data, reason=request.data.get("reason"),
                                     actor=request.user, request=request)
        return Response(_policy(policy))


class PricingPublishView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_MANAGE

    def post(self, request):
        from apps.audit.services import record_admin_action
        from apps.pricing.history import publish_prices

        reason = services.require_reason(request.data.get("reason"))
        ids = request.data.get("offering_ids")
        result = publish_prices(actor=request.user, reason=reason,
                                offering_ids=ids if isinstance(ids, list) else None)
        record_admin_action(admin=request.user, action="PRICING_PUBLISH", target=None,
                            reason=reason,
                            after={**result, "scope": "selected" if ids else "all pending"},
                            request=request)
        return Response(result)


class PricingBulkView(AdminBase, APIView):
    """Markup for a scope (provider / country / service), in two steps.

    POST {..., "confirm": false} returns what would change; the same body with
    "confirm": true and a reason applies it.
    """

    required_permission = AdminPermission.PRICING_VIEW

    def post(self, request):
        scope = request.data.get("scope") or {}
        if not request.data.get("confirm"):
            return Response(services.preview_markup(scope=scope, data=request.data))
        self.required_permission = AdminPermission.PRICING_MANAGE
        self.check_permissions(request)
        rule = services.apply_markup(scope=scope, data=request.data,
                                     reason=request.data.get("reason"), actor=request.user,
                                     request=request)
        return Response({"rule": str(rule.pk), "name": rule.name})


class ProviderCostHistoryViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    required_permission = AdminPermission.PRICING_VIEW

    def get_queryset(self):
        queryset = ProviderCostChange.objects.select_related("changed_by")
        params = self.request.query_params
        if params.get("country"):
            queryset = queryset.filter(country_code=params["country"].upper())
        if params.get("source"):
            queryset = queryset.filter(source=params["source"])
        if params.get("search"):
            queryset = queryset.filter(service_name__icontains=params["search"])
        return queryset.order_by("-created_at")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        data = [{"id": str(c.pk), "service_name": c.service_name, "country_code": c.country_code,
                 "provider_key": c.provider_key,
                 "old_cost": str(c.old_cost) if c.old_cost is not None else None,
                 "new_cost": str(c.new_cost), "currency": c.currency, "source": c.source,
                 "sync_method": c.sync_method,
                 "changed_by_email": getattr(c.changed_by, "email", None),
                 "reason": c.reason, "created_at": c.created_at} for c in page]
        return self.get_paginated_response(data)


class PricingAuditViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every pricing change: who, when, what field, old and new, why."""

    required_permission = AdminPermission.PRICING_VIEW

    def get_queryset(self):
        return AdminAction.objects.filter(PRICING_AUDIT_ACTIONS).select_related("admin").order_by(
            "-created_at")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        data = [{"id": str(a.pk), "admin_email": getattr(a.admin, "email", None),
                 "action": a.action,
                 "reason": a.reason, "before": a.before, "after": a.after,
                 "created_at": a.created_at} for a in page]
        return self.get_paginated_response(data)

