"""Referral management for staff.

Staff can review, reject, flag and reverse - but they cannot type a number
into a balance. Every action here goes through the referral services, which go
through the ledger, and every one writes an AdminAction with a mandatory
reason before it takes effect.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.audit.services import record_admin_action
from apps.common.errors import Conflict, NotFound, ValidationFailed
from apps.common.money import quantize
from apps.common.permissions import HasPermissionCode, IsSupport
from apps.referrals.models import (
    Referral,
    ReferralProgram,
    ReferralReward,
    ReferralStatus,
    ReferrerReward,
    RewardStatus,
)
from apps.referrals.services import issue_reward, reverse_reward


class AdminRiskFlagSerializer(serializers.Serializer):
    kind = serializers.CharField()
    level = serializers.CharField()
    detail = serializers.CharField()
    blocking = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class AdminReferralSerializer(serializers.ModelSerializer):
    referrer_email = serializers.CharField(source="referrer.email", read_only=True)
    referrer_id = serializers.UUIDField(source="referrer.id", read_only=True)
    referred_email = serializers.CharField(source="referred_user.email", read_only=True)
    referred_id = serializers.UUIDField(source="referred_user.id", read_only=True)
    referred_email_verified = serializers.BooleanField(
        source="referred_user.is_email_verified", read_only=True
    )
    referred_suspended = serializers.BooleanField(
        source="referred_user.is_suspended", read_only=True
    )
    reward = serializers.SerializerMethodField()
    referrer_reward = serializers.SerializerMethodField()
    risk_flags = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            "id", "code", "status", "reason", "staff_note",
            "referrer_id", "referrer_email", "referred_id", "referred_email",
            "referred_email_verified", "referred_suspended",
            "signup_ip", "risk_score", "reward", "referrer_reward", "risk_flags",
            "created_at", "eligible_at", "rewarded_at", "rejected_at",
        ]
        read_only_fields = fields

    def get_referrer_reward(self, obj: Referral):
        reward = getattr(obj, "referrer_reward", None)
        if reward is None:
            return None
        return {
            "reference": reward.reference,
            "amount": str(reward.amount),
            "status": reward.status,
            "created_at": reward.created_at,
        }

    def get_reward(self, obj: Referral):
        reward = getattr(obj, "reward", None)
        if reward is None:
            return None
        return {
            "reference": reward.reference,
            "amount": str(reward.amount),
            "currency": reward.currency,
            "status": reward.status,
            "ledger_entry_id": str(reward.ledger_entry_id) if reward.ledger_entry_id else None,
            "reversed_at": reward.reversed_at,
            "created_at": reward.created_at,
        }

    def get_risk_flags(self, obj: Referral):
        return AdminRiskFlagSerializer(obj.risk_flags.all(), many=True).data


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, min_length=5)


class AdminReferralViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsSupport, HasPermissionCode]
    required_permission = AdminPermission.REFERRAL_VIEW
    serializer_class = AdminReferralSerializer

    def get_queryset(self):
        queryset = Referral.objects.select_related(
            "referrer", "referred_user", "reward", "referrer_reward"
        ).prefetch_related("risk_flags")

        status_filter = (self.request.query_params.get("status") or "").upper()
        if status_filter and status_filter != "ALL":
            queryset = queryset.filter(status=status_filter)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(referrer__email__icontains=search)
                | Q(referred_user__email__icontains=search)
            )
        flagged = self.request.query_params.get("flagged")
        if flagged == "true":
            queryset = queryset.filter(risk_flags__isnull=False).distinct()
        return queryset.order_by("-created_at")

    def _get_referral(self) -> Referral:
        referral = self.get_queryset().filter(pk=self.kwargs["pk"]).first()
        if referral is None:
            raise NotFound("We could not find that referral.")
        return referral

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """Reward a referral the automatic policy held back.

        Issuing money needs the wallet permission, not merely the referral one.
        """
        self.required_permission = AdminPermission.REFERRAL_MANAGE
        self.check_permissions(request)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        referral = self._get_referral()

        if referral.status == ReferralStatus.REWARDED:
            raise Conflict("This referral has already been rewarded.")
        if hasattr(referral, "reward"):
            raise Conflict("This referral already has a reward.")

        reward = issue_reward(referral, actor=request.user, force=True)
        if reward is None:
            raise Conflict("This referral could not be rewarded.")

        record_admin_action(
            admin=request.user, action="REFERRAL_APPROVE", target=referral,
            reason=serializer.validated_data["reason"],
            before={"status": referral.status},
            after={"status": ReferralStatus.REWARDED, "reward_reference": reward.reference,
                   "amount": str(reward.amount)},
            request=request,
        )
        referral.refresh_from_db()
        return Response(AdminReferralSerializer(referral).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        self.required_permission = AdminPermission.REFERRAL_MANAGE
        self.check_permissions(request)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        referral = self._get_referral()
        if referral.status == ReferralStatus.REWARDED:
            raise Conflict("Reverse the reward before rejecting this referral.")

        reason = serializer.validated_data["reason"]
        with transaction.atomic():
            record_admin_action(
                admin=request.user, action="REFERRAL_REJECT", target=referral,
                reason=reason, before={"status": referral.status},
                after={"status": ReferralStatus.REJECTED}, request=request,
            )
            Referral.objects.filter(pk=referral.pk).update(
                status=ReferralStatus.REJECTED,
                reason="This invitation did not qualify.",
                staff_note=reason[:500],
                rejected_at=timezone.now(),
                reviewed_by=request.user,
            )
        referral.refresh_from_db()
        return Response(AdminReferralSerializer(referral).data)

    @action(detail=True, methods=["post"], url_path="flag")
    def flag(self, request, pk=None):
        self.required_permission = AdminPermission.REFERRAL_MANAGE
        self.check_permissions(request)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        referral = self._get_referral()

        reason = serializer.validated_data["reason"]
        with transaction.atomic():
            record_admin_action(
                admin=request.user, action="REFERRAL_FLAG", target=referral,
                reason=reason, before={"status": referral.status},
                after={"status": ReferralStatus.FRAUD_FLAGGED}, request=request,
            )
            Referral.objects.filter(pk=referral.pk).update(
                status=ReferralStatus.FRAUD_FLAGGED,
                reason="We are reviewing this invitation.",
                staff_note=reason[:500],
                reviewed_by=request.user,
            )
        referral.refresh_from_db()
        return Response(AdminReferralSerializer(referral).data)

    @action(detail=True, methods=["post"], url_path="reverse-reward")
    def reverse(self, request, pk=None):
        """Claw back promotional credit. Needs the wallet-adjustment permission."""
        self.required_permission = AdminPermission.WALLET_ADJUST
        self.check_permissions(request)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        referral = self._get_referral()

        reward = ReferralReward.objects.filter(referral=referral).first()
        if reward is None:
            raise Conflict("This referral has no reward to reverse.")
        if reward.status == RewardStatus.REVERSED:
            raise Conflict("This reward has already been reversed.")

        reason = serializer.validated_data["reason"]
        with transaction.atomic():
            reward = reverse_reward(reward, admin=request.user, reason=reason)
            record_admin_action(
                admin=request.user, action="REFERRAL_REWARD_REVERSE", target=referral,
                reason=reason,
                before={"reward_status": RewardStatus.ISSUED, "amount": str(reward.amount)},
                after={"reward_status": reward.status,
                       "reversal_entry_id": str(reward.reversal_entry_id or "")},
                request=request,
            )
        referral.refresh_from_db()
        return Response(AdminReferralSerializer(referral).data)


class AdminReferralAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsSupport, HasPermissionCode]
    required_permission = AdminPermission.REFERRAL_VIEW

    def get(self, request):
        counts = dict(
            Referral.objects.values_list("status").annotate(n=Count("id"))
        )
        total = sum(counts.values())
        rewarded = counts.get(ReferralStatus.REWARDED, 0)
        rejected = counts.get(ReferralStatus.REJECTED, 0)
        flagged = counts.get(ReferralStatus.FRAUD_FLAGGED, 0)

        issued = ReferralReward.objects.filter(status=RewardStatus.ISSUED).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")
        reversed_total = ReferralReward.objects.filter(status=RewardStatus.REVERSED).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        referrer_issued = ReferrerReward.objects.filter(status=RewardStatus.ISSUED).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        # Cost per acquisition counts only referrals we actually paid for.
        # Rejected and fraudulent sign-ups are not acquisitions.
        acquisition_cost = quantize(issued / rewarded) if rewarded else Decimal("0.00")
        conversion = round((rewarded / total) * 100, 1) if total else 0.0
        funnel = _referred_funnel()

        return Response(
            {
                "registrations": total,
                "pending": counts.get(ReferralStatus.PENDING, 0),
                "eligible": counts.get(ReferralStatus.ELIGIBLE, 0),
                "rewarded": rewarded,
                "rejected": rejected,
                "fraud_flagged": flagged,
                "promotional_credit_issued": str(quantize(issued)),
                "promotional_credit_reversed": str(quantize(reversed_total)),
                "average_acquisition_cost": str(acquisition_cost),
                "conversion_rate": conversion,
                "referrer_credit_issued": str(quantize(referrer_issued)),
                # Both bonuses at face value: the most the programme has promised.
                "total_bonus_cost": str(quantize(issued + referrer_issued)),
                **funnel,
            }
        )


def _percent(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _referred_funnel() -> dict:
    """What invited people went on to do: top up, buy, come back - and pay.

    Revenue counts delivered, unrefunded orders only, and its cash part is
    money the customer actually paid - the figure to set against the bonuses.
    """
    from apps.orders.models import Order, RefundStatus
    from apps.wallet.models import FundType, LedgerDirection, LedgerEntryType, WalletLedgerEntry

    invited = Referral.objects.values("referred_user")
    invited_count = Referral.objects.count()
    verified = Referral.objects.filter(referred_user__is_email_verified=True).count()
    topped_up = (
        WalletLedgerEntry.objects.filter(
            wallet__user__in=invited, entry_type=LedgerEntryType.DEPOSIT,
            direction=LedgerDirection.CREDIT, funds=FundType.CASH,
        ).values("wallet__user").distinct().count()
    )
    delivered = Order.objects.filter(user__in=invited, code_received_at__isnull=False) \
        .exclude(refund_status=RefundStatus.COMPLETED)
    buyers = delivered.values("user").distinct().count()
    repeat = delivered.values("user").annotate(n=Count("id")).filter(n__gte=2).count()
    totals = delivered.aggregate(revenue=Sum("price"), cash=Sum("cash_amount"))
    return {
        "invited_verified": verified,
        "invited_verified_rate": _percent(verified, invited_count),
        "invited_topped_up": topped_up,
        "invited_topped_up_rate": _percent(topped_up, invited_count),
        "invited_buyers": buyers,
        "invited_repeat_buyers": repeat,
        "invited_repeat_rate": _percent(repeat, buyers),
        "invited_orders": delivered.count(),
        "invited_revenue": str(quantize(totals["revenue"] or Decimal("0.00"))),
        "invited_cash_revenue": str(quantize(totals["cash"] or Decimal("0.00"))),
    }


class ReferralProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralProgram
        fields = [
            "is_enabled", "signup_bonus", "currency", "max_monthly_successful_referrals",
            "velocity_per_hour", "require_email_verification", "require_phone_verification",
            "require_first_deposit", "min_first_deposit", "referrer_bonus",
            "updated_at",
        ]
        read_only_fields = ["currency", "updated_at"]


class AdminReferralProgramView(APIView):
    """Programme configuration. Changing what the platform pays out is a
    money decision, so it sits behind the pricing permission (super admin)."""

    permission_classes = [IsAuthenticated, IsSupport, HasPermissionCode]
    required_permission = AdminPermission.REFERRAL_VIEW

    def get(self, request):
        return Response(ReferralProgramSerializer(ReferralProgram.load()).data)

    def patch(self, request):
        self.required_permission = AdminPermission.PRICING_MANAGE
        self.check_permissions(request)

        program = ReferralProgram.load()
        serializer = ReferralProgramSerializer(program, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field in ("signup_bonus", "referrer_bonus", "min_first_deposit"):
            if Decimal(str(serializer.validated_data.get(field, getattr(program, field)))) < 0:
                raise ValidationFailed("Amounts cannot be negative.")

        before = ReferralProgramSerializer(program).data
        with transaction.atomic():
            updated = serializer.save(updated_by=request.user)
            record_admin_action(
                admin=request.user, action="REFERRAL_PROGRAM_UPDATE", target=updated,
                reason=str(request.data.get("reason", "") or "Referral programme update")[:500],
                before={k: str(v) for k, v in before.items()},
                after={k: str(v) for k, v in ReferralProgramSerializer(updated).data.items()},
                request=request,
            )
        return Response(ReferralProgramSerializer(updated).data)
