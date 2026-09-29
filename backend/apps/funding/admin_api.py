"""Admin > Provider funding.

Seeing balances, alerts and the cash-flow view needs PRICING_VIEW - the same
people who can see what numbers cost us. Changing reserve levels or recording
a top-up needs PROVIDER_MANAGE (super admins). Nothing here can move money:
a recorded top-up is bookkeeping for a payment made by hand on the provider's
website.
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.common.errors import NotFound
from apps.funding import services
from apps.funding.models import ProviderAlert, ProviderTopUp, TopUpMethod


def _top_up(top_up: ProviderTopUp) -> dict:
    return {
        "id": str(top_up.id),
        "amount": str(top_up.amount),
        "currency": top_up.currency,
        "method": top_up.method,
        "method_label": top_up.get_method_display(),
        "external_reference": top_up.external_reference,
        "paid_ghs": str(top_up.paid_ghs) if top_up.paid_ghs is not None else None,
        "note": top_up.note,
        "balance_before": str(top_up.balance_before) if top_up.balance_before is not None else None,
        "confirmed_at": top_up.confirmed_at,
        "confirmed_balance": (str(top_up.confirmed_balance)
                              if top_up.confirmed_balance is not None else None),
        "recorded_by": top_up.recorded_by.email,
        "created_at": top_up.created_at,
    }


def _alert(alert: ProviderAlert) -> dict:
    return {
        "id": str(alert.id),
        "provider": alert.provider.name,
        "kind": alert.kind,
        "kind_label": alert.get_kind_display(),
        "severity": alert.severity,
        "message": alert.message,
        "created_at": alert.created_at,
    }


def _account(adapter_key: str):
    provider = services._funded_providers().filter(adapter_key=adapter_key).first()
    if provider is None:
        raise NotFound("No such provider.")
    return services.account_for(provider)


class FundingOverviewView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request):
        accounts = [services.account_report(services.account_for(provider))
                    for provider in services._funded_providers()]
        alerts = ProviderAlert.objects.select_related("provider")[:30]
        return Response({
            "accounts": accounts,
            "cash_flow": services.cash_flow(),
            "alerts": [_alert(alert) for alert in alerts],
            "top_up_methods": [{"value": value, "label": label}
                               for value, label in TopUpMethod.choices],
            "can_manage": request.user.has_admin_permission(AdminPermission.PROVIDER_MANAGE),
        })


class FundingAccountView(AdminBase, APIView):
    required_permission = AdminPermission.PROVIDER_MANAGE

    def patch(self, request, adapter_key: str):
        account = services.update_account(
            _account(adapter_key), data=request.data, reason=request.data.get("reason"),
            actor=request.user, request=request,
        )
        return Response(services.account_report(account))


class FundingSyncView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def post(self, request, adapter_key: str):
        account = services.sync_balance(_account(adapter_key).provider)
        return Response(services.account_report(account))


class FundingTopUpView(AdminBase, APIView):
    required_permission = AdminPermission.PRICING_VIEW

    def get(self, request, adapter_key: str):
        account = _account(adapter_key)
        top_ups = account.top_ups.select_related("recorded_by")[:100]
        return Response({"results": [_top_up(top_up) for top_up in top_ups]})

    def post(self, request, adapter_key: str):
        self.required_permission = AdminPermission.PROVIDER_MANAGE
        self.check_permissions(request)
        top_up = services.record_top_up(_account(adapter_key), data=request.data,
                                        actor=request.user, request=request)
        return Response(_top_up(top_up), status=201)
