"""Agents: the staff side (register, set a rate, record a payout) and the
agent's own page.

Registering an agent or changing a rate decides what the platform pays out, so
it sits behind the pricing permission, like the referral programme. Recording a
payout says money left the business, so it needs the wallet permission.
"""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.accounts.models import User
from apps.common.errors import NotFound
from apps.common.permissions import HasPermissionCode, IsActiveUser, IsSupport
from apps.referrals import agents
from apps.referrals.models import Agent, AgentCommission, AgentPayout
from apps.referrals.serializers import mask_email
from apps.referrals.services import code_for

RECENT = 50


def _commissions(agent: Agent, *, masked: bool) -> list[dict]:
    rows = (AgentCommission.objects.filter(agent=agent).select_related("customer")
            .order_by("-created_at")[:RECENT])
    return [
        {
            "id": str(row.pk),
            "kind": row.kind,
            "reference": row.source_reference,
            "customer": mask_email(row.customer.email) if masked else row.customer.email,
            "base_amount": str(row.base_amount),
            "percent": str(row.percent),
            "amount": str(row.amount),
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _payouts(agent: Agent) -> list[dict]:
    return [
        {"id": str(row.pk), "amount": str(row.amount), "reference": row.reference,
         "note": row.note, "created_at": row.created_at}
        for row in AgentPayout.objects.filter(agent=agent).order_by("-created_at")[:RECENT]
    ]


def _agent(agent: Agent) -> dict:
    code = code_for(agent.user)
    return {
        "id": str(agent.pk),
        "email": agent.user.email,
        "full_name": agent.user.full_name,
        "commission_percent": str(agent.commission_percent),
        "is_active": agent.is_active,
        "payout_details": agent.payout_details,
        "code": code.code,
        "share_url": code.share_url,
        "created_at": agent.created_at,
        **agents.totals(agent),
    }


class RegisterAgentSerializer(serializers.Serializer):
    email = serializers.EmailField()
    commission_percent = serializers.DecimalField(max_digits=5, decimal_places=2,
                                                  required=False, allow_null=True)
    payout_details = serializers.CharField(max_length=120, required=False, allow_blank=True)


class UpdateAgentSerializer(serializers.Serializer):
    commission_percent = serializers.DecimalField(max_digits=5, decimal_places=2,
                                                  required=False)
    is_active = serializers.BooleanField(required=False)
    payout_details = serializers.CharField(max_length=120, required=False, allow_blank=True)


class PayoutSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(max_length=80)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class _Staff(APIView):
    permission_classes = [IsAuthenticated, IsSupport, HasPermissionCode]
    required_permission = AdminPermission.REFERRAL_VIEW

    def _need(self, request, permission) -> None:
        self.required_permission = permission
        self.check_permissions(request)

    def _get(self, pk) -> Agent:
        agent = Agent.objects.select_related("user").filter(pk=pk).first()
        if agent is None:
            raise NotFound("We could not find that agent.")
        return agent


class AdminAgentsView(_Staff):
    def get(self, request):
        agents.sync_all()
        return Response(
            {"default_percent": str(agents.default_percent()),
             "results": [_agent(a) for a in Agent.objects.select_related("user")]}
        )

    def post(self, request):
        self._need(request, AdminPermission.PRICING_MANAGE)
        serializer = RegisterAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = User.objects.filter(email__iexact=data["email"].strip()).first()
        if user is None:
            raise NotFound("No account uses that email. Ask them to sign up first.")
        agent = agents.register(
            user=user, percent=data.get("commission_percent"),
            payout_details=data.get("payout_details", ""), admin=request.user, request=request,
        )
        return Response(_agent(agent), status=201)


class AdminAgentView(_Staff):
    def get(self, request, pk):
        agent = self._get(pk)
        agents.sync(agent)
        return Response({**_agent(agent), "commissions": _commissions(agent, masked=False),
                         "payouts": _payouts(agent)})

    def patch(self, request, pk):
        self._need(request, AdminPermission.PRICING_MANAGE)
        serializer = UpdateAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        agent = agents.update(
            self._get(pk), percent=data.get("commission_percent"),
            is_active=data.get("is_active"), payout_details=data.get("payout_details"),
            admin=request.user, request=request,
        )
        return Response(_agent(agent))


class AdminAgentPayoutView(_Staff):
    def post(self, request, pk):
        self._need(request, AdminPermission.WALLET_ADJUST)
        serializer = PayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agent = self._get(pk)
        agents.record_payout(agent, admin=request.user, request=request,
                             **serializer.validated_data)
        return Response(_agent(agent), status=201)


class MyAgentView(APIView):
    """The agent's own page. Says so plainly when the user is not an agent."""

    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        agent = Agent.objects.select_related("user").filter(user=request.user).first()
        if agent is None:
            return Response({"is_agent": False})
        agents.sync(agent)
        summary = _agent(agent)
        for private in ("id", "email", "full_name"):
            summary.pop(private)
        return Response({"is_agent": True, **summary,
                         "commissions": _commissions(agent, masked=True),
                         "payouts": _payouts(agent)})
