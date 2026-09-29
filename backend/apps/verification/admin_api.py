"""Admin > Providers: which suppliers exist, which may sell, and how they are doing.

Reading needs PRICING_VIEW (provider costs and balances are finance data).
Switching a provider on or off, and recording or withdrawing its written
permission to resell, need PROVIDER_MANAGE; each change carries a reason and is
written to the AdminAction log with what it changed.

Every figure is measured, never estimated: API timings come from our own
recorded calls (and say since when), success rates from our own orders. What
cannot be measured is shown as unknown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.audit.services import record_admin_action
from apps.catalog.models import Provider, ProviderService
from apps.common.errors import NotFound, ValidationFailed

WINDOW_DAYS = 30


def _ts(value) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()


def _rate(numerator: int, denominator: int) -> str | None:
    if not denominator:
        return None
    return f"{numerator * 100 / denominator:.1f}"


def _order_metrics(provider: Provider) -> dict:
    from apps.orders.models import ACTIVE_ORDER_STATUSES, Order, OrderStatus

    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    orders = Order.objects.filter(provider=provider, created_at__gte=since)
    sent = orders.count()
    assigned = orders.exclude(phone_number="")
    finished_assigned = assigned.exclude(status__in=ACTIVE_ORDER_STATUSES)
    delivered = finished_assigned.filter(code_received_at__isnull=False).count()
    return {
        "window_days": WINDOW_DAYS,
        "orders": sent,
        "numbers_assigned": assigned.count(),
        # Of orders sent to the provider, how many got a number.
        "purchase_success_rate": _rate(assigned.count(), sent),
        # Of finished orders that had a number, how many received a code.
        "sms_delivered": delivered,
        "sms_success_rate": _rate(delivered, finished_assigned.count()),
        "refunded": orders.filter(status=OrderStatus.REFUNDED).count(),
        "in_flight": orders.filter(status__in=ACTIVE_ORDER_STATUSES).count(),
    }


def _report(provider: Provider) -> dict:
    from apps.catalog.marketplace import sellable_offerings
    from apps.funding.models import ProviderAccount
    from apps.verification.registry import available_adapters, call_stats, get_provider

    registered = provider.adapter_key in available_adapters()
    adapter = get_provider(provider.adapter_key) if registered else None
    stats = call_stats(provider.adapter_key)
    offerings = ProviderService.objects.filter(provider=provider)
    account = ProviderAccount.objects.filter(provider=provider).first()

    return {
        "adapter_key": provider.adapter_key,
        "name": provider.name,
        "is_primary": provider.adapter_key == settings.VERIFYGH["VERIFICATION_PROVIDER"],
        "is_enabled": provider.is_enabled,
        "priority": provider.priority,
        "registered": registered,
        "configured": bool(adapter and adapter.is_configured),
        "resale_authorized": provider.resale_authorized,
        "authorization_reference": provider.authorization_reference,
        "authorized_at": provider.authorized_at,
        "authorized_by": provider.authorized_by.email if provider.authorized_by else None,
        # Everything a customer could buy through it right now.
        "selling": bool(provider.is_enabled and provider.resale_authorized and registered),
        "capabilities": {
            "balance": bool(adapter and adapter.supports_balance),
            "account_funding": bool(adapter and adapter.supports_account_funding),
            "webhooks": bool(adapter and adapter.supports_webhooks),
            "webhooks_active": bool(adapter and adapter.accepts_webhooks),
            "issue_reports": bool(adapter and adapter.supports_issue_reports),
        },
        "api": {
            "since": _ts(stats.get("since")),
            "calls": stats.get("calls", 0),
            "failures": stats.get("failures", 0),
            "average_ms": round(stats["avg_ms"]) if stats.get("avg_ms") is not None else None,
            "last_success_at": _ts(stats.get("last_success_at")),
            "last_success_operation": stats.get("last_success_operation", ""),
            "last_failure_at": _ts(stats.get("last_failure_at")),
            "last_failure_operation": stats.get("last_failure_operation", ""),
            "last_failure_error": stats.get("last_failure_error", ""),
        },
        "catalogue": {
            "offerings": offerings.count(),
            "in_stock": offerings.filter(is_available=True).count(),
            "listed_to_customers": sellable_offerings().filter(provider=provider).count(),
            "countries": sorted(set(offerings.values_list("country__code", flat=True))),
            "last_synced_at": provider.last_synced_at,
            "last_sync_error": provider.last_sync_error[:300],
        },
        "orders": _order_metrics(provider),
        "funding": {
            "status": account.status if account else None,
            "balance": str(account.available) if account and account.available is not None
            else None,
            "currency": account.currency if account else None,
            "last_synced_at": account.last_synced_at if account else None,
            "last_sync_error": account.last_sync_error if account else "",
        },
    }


def _provider(adapter_key: str) -> Provider:
    provider = Provider.objects.select_related("authorized_by").filter(
        adapter_key=adapter_key).first()
    if provider is None:
        raise NotFound("No such provider.")
    return provider


def _reason(value) -> str:
    reason = str(value or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason for this change (at least 5 characters).")
    return reason[:500]


def _state(provider: Provider) -> dict:
    return {"is_enabled": provider.is_enabled, "resale_authorized": provider.resale_authorized,
            "authorization_reference": provider.authorization_reference}


def _refresh_listings() -> None:
    from apps.funding.services import refresh_marketplace

    refresh_marketplace()


class ProvidersView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request):
        providers = Provider.objects.select_related("authorized_by").exclude(
            Q(adapter_key="mock") & ~Q(adapter_key=settings.VERIFYGH["VERIFICATION_PROVIDER"])
        ).order_by("priority", "name")
        return Response({
            "primary": settings.VERIFYGH["VERIFICATION_PROVIDER"],
            "providers": [_report(provider) for provider in providers],
            "can_manage": request.user.has_admin_permission(AdminPermission.PROVIDER_MANAGE),
        })


class ProviderStatusView(AdminBase, APIView):
    """Switch a provider on or off. Off: nothing new is ordered through it, and
    it is not called - its orders and history are untouched."""

    required_permission = AdminPermission.PROVIDER_MANAGE

    def post(self, request, adapter_key: str):
        reason = _reason(request.data.get("reason"))
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationFailed("Say whether the provider should be enabled.")
        with transaction.atomic():
            provider = Provider.objects.select_for_update().get(pk=_provider(adapter_key).pk)
            before = _state(provider)
            provider.is_enabled = enabled
            provider.save(update_fields=["is_enabled", "updated_at"])
            record_admin_action(
                admin=request.user,
                action="PROVIDER_ENABLED" if enabled else "PROVIDER_DISABLED",
                target=provider, reason=reason, before=before, after=_state(provider),
                request=request,
            )
        _refresh_listings()
        return Response(_report(_provider(adapter_key)))


class ProviderAuthorizationView(AdminBase, APIView):
    """Record, or withdraw, a provider's written permission to resell its numbers.

    Granting needs the evidence - where and when the provider said yes - so the
    record answers "on what basis did we sell this?" without anyone's memory.
    """

    required_permission = AdminPermission.PROVIDER_MANAGE

    def post(self, request, adapter_key: str):
        reason = _reason(request.data.get("reason"))
        authorized = request.data.get("authorized")
        if not isinstance(authorized, bool):
            raise ValidationFailed("Say whether resale is authorised.")
        reference = str(request.data.get("reference") or "").strip()[:300]
        if authorized and len(reference) < 10:
            raise ValidationFailed(
                "Describe the written permission: who at the provider agreed, how "
                "(email, ticket, contract) and when.")
        with transaction.atomic():
            provider = Provider.objects.select_for_update().get(pk=_provider(adapter_key).pk)
            before = _state(provider)
            provider.resale_authorized = authorized
            if authorized:
                provider.authorization_reference = reference
                provider.authorized_at = timezone.now()
                provider.authorized_by = request.user
            else:
                provider.authorization_reference = (
                    f"Withdrawn {timezone.now():%Y-%m-%d}: {reason}"[:300])
                provider.authorized_at = None
                provider.authorized_by = None
            provider.save(update_fields=["resale_authorized", "authorization_reference",
                                         "authorized_at", "authorized_by", "updated_at"])
            record_admin_action(
                admin=request.user,
                action="PROVIDER_RESALE_AUTHORIZED" if authorized
                else "PROVIDER_RESALE_WITHDRAWN",
                target=provider, reason=reason, before=before, after=_state(provider),
                request=request,
            )
        _refresh_listings()
        return Response(_report(_provider(adapter_key)))
