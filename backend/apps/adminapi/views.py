"""Admin API.

Two rules run through every view here:

1. **Least privilege.** Each endpoint declares `required_permission`, checked
   against the role matrix in `apps/accounts/constants.py`. A SUPPORT user can
   read a wallet but cannot adjust one; only a SUPER_ADMIN can change pricing.
2. **Nothing sensitive happens without a reason.** Suspensions, wallet
   adjustments and refunds all require a written reason and write an immutable
   `AdminAction` row before the effect is applied.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import staff
from apps.accounts.constants import STAFF_ROLES, AdminPermission, Role
from apps.accounts.models import LoginAttempt, User
from apps.adminapi.serializers import (
    AdminActionSerializer,
    AdminCountrySerializer,
    AdminOfferingSerializer,
    AdminOrderSerializer,
    AdminPaymentDetailSerializer,
    AdminPaymentSerializer,
    AdminRefundSerializer,
    AdminServiceSerializer,
    AdminUserSerializer,
    AuditLogSerializer,
    ChangeEmailSerializer,
    ChangeRoleSerializer,
    ExchangeRateSerializer,
    InviteStaffSerializer,
    IssueRefundSerializer,
    PriceChangeSerializer,
    PricingRuleSerializer,
    ResolveFlagSerializer,
    SuspendUserSerializer,
    SuspiciousActivitySerializer,
    WalletAdjustmentSerializer,
)
from apps.audit.models import AdminAction, AuditLog, SuspiciousActivity
from apps.audit.services import record_admin_action, resolve_flag
from apps.catalog.models import Country, ProviderService, Service
from apps.common.errors import Conflict, NotFound, ValidationFailed
from apps.common.idempotency import generate
from apps.common.permissions import HasPermissionCode, IsSupport
from apps.orders.models import Order, OrderStatus, Refund, RefundReason
from apps.orders.services import cancel_order as cancel_order_service
from apps.orders.services import issue_refund
from apps.payments.models import Payment, PaymentStatus
from apps.pricing.models import ExchangeRate, PricingPolicy, PricingRule
from apps.pricing.rates import record_rate
from apps.wallet.models import LedgerDirection, WalletLedgerEntry
from apps.wallet.serializers import LedgerEntrySerializer
from apps.wallet.services import adjust, get_or_create_wallet, verify_wallet_integrity

logger = logging.getLogger("verifygh.admin")

MONEY = DecimalField(max_digits=18, decimal_places=4)


class AdminBase:
    permission_classes = [IsAuthenticated, IsSupport, HasPermissionCode]
    required_permission: str | None = None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class AdminOverviewView(AdminBase, APIView):
    required_permission = AdminPermission.METRICS_VIEW

    def get(self, request):
        now = timezone.now()
        today = timezone.localtime().date()
        month_ago = now - timedelta(days=30)

        orders = Order.objects.all()
        payments = Payment.objects.filter(status=PaymentStatus.SUCCESS)

        revenue = orders.filter(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED]
        ).aggregate(total=Sum("price"))["total"] or Decimal("0.00")

        revenue_today = orders.filter(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED],
            created_at__date=today,
        ).aggregate(total=Sum("price"))["total"] or Decimal("0.00")

        # Provider cost in GHS, using the rate frozen on each order.
        cost_expression = ExpressionWrapper(
            F("provider_cost") * F("exchange_rate"), output_field=MONEY
        )
        provider_cost = orders.filter(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED]
        ).aggregate(total=Sum(cost_expression))["total"] or Decimal("0.0000")

        refunds = Refund.objects.filter(status="COMPLETED").aggregate(
            total=Sum("amount"), count=Count("id")
        )
        refund_total = refunds["total"] or Decimal("0.00")

        gross_margin = Decimal(revenue) - Decimal(provider_cost)
        margin_percent = (
            (gross_margin / Decimal(revenue) * 100).quantize(Decimal("0.01"))
            if revenue
            else Decimal("0.00")
        )

        return Response(
            {
                "users": {
                    "total": User.objects.count(),
                    "active_30d": User.objects.filter(last_login__gte=month_ago).count(),
                    "new_today": User.objects.filter(created_at__date=today).count(),
                    "suspended": User.objects.filter(is_suspended=True).count(),
                },
                "revenue": {
                    "total": str(revenue),
                    "today": str(revenue_today),
                    "provider_cost": str(Decimal(provider_cost).quantize(Decimal("0.01"))),
                    "gross_margin": str(gross_margin.quantize(Decimal("0.01"))),
                    "margin_percent": str(margin_percent),
                    "currency": "GHS",
                },
                "orders": {
                    "total": orders.count(),
                    "today": orders.filter(created_at__date=today).count(),
                    "successful": orders.filter(status=OrderStatus.COMPLETED).count(),
                    "code_received": orders.filter(status=OrderStatus.CODE_RECEIVED).count(),
                    "failed": orders.filter(
                        status__in=[OrderStatus.FAILED, OrderStatus.EXPIRED]
                    ).count(),
                    "active": orders.filter(
                        status__in=[
                            OrderStatus.PROCESSING,
                            OrderStatus.NUMBER_ASSIGNED,
                            OrderStatus.WAITING_FOR_CODE,
                        ]
                    ).count(),
                },
                "payments": {
                    "momo_total": str(
                        payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
                    ),
                    "momo_today": str(
                        payments.filter(created_at__date=today).aggregate(
                            total=Sum("amount")
                        )["total"]
                        or Decimal("0.00")
                    ),
                    "count": payments.count(),
                    "failed": Payment.objects.filter(status=PaymentStatus.FAILED).count(),
                },
                "refunds": {"total": str(refund_total), "count": refunds["count"] or 0},
                "flags": {
                    "open": SuspiciousActivity.objects.filter(resolved=False).count(),
                    "high": SuspiciousActivity.objects.filter(
                        resolved=False, level="HIGH"
                    ).count(),
                },
            }
        )


#: Orders that earned revenue: the customer got (or is reading) their code.
EARNING = [OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED]
#: Orders that ended without earning. REFUNDED is counted apart from these.
UNSUCCESSFUL = [OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED]


def _by_day(queryset, **aggregates) -> dict:
    """{local date: row} for one queryset, grouped on created_at."""
    rows = (queryset.annotate(day=TruncDate("created_at")).values("day")
            .annotate(**aggregates).order_by("day"))
    return {row["day"]: row for row in rows}


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _period(start, end) -> dict:
    """Everything the dashboard charts, day by day, for [start, end) local dates.

    Every day in the range is present, with zeros on a quiet day - a chart
    that skips empty days draws a busy week where there was a dead one.
    """
    tz = timezone.get_current_timezone()
    lower = timezone.make_aware(datetime.combine(start, time.min), tz)
    upper = timezone.make_aware(datetime.combine(end, time.min), tz)
    window = Q(created_at__gte=lower, created_at__lt=upper)
    cost = ExpressionWrapper(F("provider_cost") * F("exchange_rate"), output_field=MONEY)
    earning = Q(status__in=EARNING)

    orders = _by_day(
        Order.objects.filter(window),
        total=Count("id"),
        completed=Count("id", filter=earning),
        refunded=Count("id", filter=Q(status=OrderStatus.REFUNDED)),
        failed=Count("id", filter=Q(status__in=UNSUCCESSFUL)),
        revenue=Sum("price", filter=earning),
        cost=Sum(cost, filter=earning),
    )
    deposits = _by_day(
        Payment.objects.filter(window, status=PaymentStatus.SUCCESS),
        amount=Sum("amount"), count=Count("id"),
    )
    signups = _by_day(
        User.objects.filter(window),
        total=Count("id"), verified=Count("id", filter=Q(is_email_verified=True)),
    )

    series = []
    day = start
    while day < end:
        o, d, s = orders.get(day, {}), deposits.get(day, {}), signups.get(day, {})
        revenue, spent = _money(o.get("revenue")), _money(o.get("cost"))
        total = o.get("total", 0)
        series.append({
            "date": str(day),
            "revenue": str(revenue),
            "cost": str(spent),
            "profit": str(revenue - spent),
            "orders": total,
            "completed": o.get("completed", 0),
            "refunded": o.get("refunded", 0),
            "failed": o.get("failed", 0),
            "active": total - o.get("completed", 0) - o.get("refunded", 0) - o.get("failed", 0),
            "deposits": str(_money(d.get("amount"))),
            "deposit_count": d.get("count", 0),
            "signups": s.get("total", 0),
            "verified_signups": s.get("verified", 0),
        })
        day += timedelta(days=1)

    def total(key, money=False):
        values = [Decimal(row[key]) if money else row[key] for row in series]
        return str(sum(values, Decimal("0.00"))) if money else sum(values)

    completed, refunded, failed = total("completed"), total("refunded"), total("failed")
    finished = completed + refunded + failed
    totals = {
        "revenue": total("revenue", money=True),
        "cost": total("cost", money=True),
        "profit": total("profit", money=True),
        "orders": total("orders"),
        "completed": completed,
        "refunded": refunded,
        "failed": failed,
        "deposits": total("deposits", money=True),
        "deposit_count": total("deposit_count"),
        "signups": total("signups"),
        "verified_signups": total("verified_signups"),
        "success_rate": round(completed / finished * 100, 1) if finished else None,
    }
    return {"series": series, "totals": totals}


class AdminChartsView(AdminBase, APIView):
    required_permission = AdminPermission.METRICS_VIEW

    def get(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 14)), 1), 90)
        except (TypeError, ValueError):
            days = 14
        since = timezone.now() - timedelta(days=days)

        # The trend: the last `days` local days including today, and the same
        # length just before it for the "vs previous period" comparison.
        end = timezone.localdate() + timedelta(days=1)
        current = _period(end - timedelta(days=days), end)
        previous = _period(end - timedelta(days=2 * days), end - timedelta(days=days))

        revenue_series = list(
            Order.objects.filter(
                created_at__gte=since,
                status__in=[OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED],
            )
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(revenue=Sum("price"), orders=Count("id"))
            .order_by("day")
        )

        orders_series = list(
            Order.objects.filter(created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                total=Count("id"),
                successful=Count("id", filter=Q(status=OrderStatus.COMPLETED)),
                failed=Count(
                    "id", filter=Q(status__in=[OrderStatus.FAILED, OrderStatus.EXPIRED])
                ),
            )
            .order_by("day")
        )

        popular = list(
            Order.objects.filter(created_at__gte=since)
            .values("service__slug", "service__name")
            .annotate(orders=Count("id"), revenue=Sum("price"))
            .order_by("-orders")[:10]
        )

        networks = list(
            Payment.objects.filter(created_at__gte=since, status=PaymentStatus.SUCCESS)
            .values("network")
            .annotate(count=Count("id"), amount=Sum("amount"))
            .order_by("-amount")
        )

        total_orders = Order.objects.filter(created_at__gte=since).count()
        failed_orders = Order.objects.filter(
            created_at__gte=since, status__in=[OrderStatus.FAILED, OrderStatus.EXPIRED]
        ).count()

        return Response(
            {
                "days": days,
                "revenue": [
                    {
                        "date": str(row["day"]),
                        "revenue": str(row["revenue"] or 0),
                        "orders": row["orders"],
                    }
                    for row in revenue_series
                ],
                "orders": [
                    {
                        "date": str(row["day"]),
                        "total": row["total"],
                        "successful": row["successful"],
                        "failed": row["failed"],
                    }
                    for row in orders_series
                ],
                "popular_services": [
                    {
                        "slug": row["service__slug"],
                        "name": row["service__name"],
                        "orders": row["orders"],
                        "revenue": str(row["revenue"] or 0),
                    }
                    for row in popular
                ],
                "payment_methods": [
                    {
                        "network": row["network"],
                        "count": row["count"],
                        "amount": str(row["amount"] or 0),
                    }
                    for row in networks
                ],
                "failure_rate": round((failed_orders / total_orders * 100), 2)
                if total_orders
                else 0.0,
                "series": current["series"],
                "totals": current["totals"],
                "previous_totals": previous["totals"],
            }
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class AdminUserViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       viewsets.GenericViewSet):
    serializer_class = AdminUserSerializer
    required_permission = AdminPermission.USER_VIEW

    def get_queryset(self):
        queryset = User.objects.select_related("wallet").annotate(
            order_count=Count("orders", distinct=True),
            open_flags=Count(
                "suspicious_activities",
                filter=Q(suspicious_activities__resolved=False),
                distinct=True,
            ),
        )
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(full_name__icontains=search)
                | Q(phone__icontains=search)
            )
        if self.request.query_params.get("suspended") == "true":
            queryset = queryset.filter(is_suspended=True)
        if self.request.query_params.get("flagged") == "true":
            queryset = queryset.filter(open_flags__gt=0)
        verified = self.request.query_params.get("verified")
        if verified in ("true", "false"):
            queryset = queryset.filter(is_email_verified=verified == "true")
        role = self.request.query_params.get("role")
        if role:
            queryset = queryset.filter(role=role.upper())
        if self.request.query_params.get("staff") == "true":
            queryset = queryset.filter(role__in=STAFF_ROLES)
        if self.request.query_params.get("former_staff") == "true":
            # Once held staff access (from the admin log) - the one kind of
            # customer account that may be given a staff role again.
            queryset = queryset.filter(role=Role.USER, pk__in=self._staff_history())
        return queryset.order_by("-created_at")

    def _staff_history(self) -> set[str]:
        if not hasattr(self, "_staff_history_ids"):
            self._staff_history_ids = staff.staff_history_ids()
        return self._staff_history_ids

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "staff_history": self._staff_history()}

    def _get_user(self) -> User:
        user = User.objects.select_related("wallet").filter(pk=self.kwargs["pk"]).first()
        if user is None:
            raise NotFound("We could not find that user.")
        return user

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self.required_permission = AdminPermission.USER_SUSPEND
        self.check_permissions(request)

        serializer = SuspendUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = self._get_user()

        if target.role in (Role.ADMIN, Role.SUPER_ADMIN) and request.user.role != Role.SUPER_ADMIN:
            raise Conflict("Only a super admin can suspend another admin.")
        if target.pk == request.user.pk:
            raise ValidationFailed("You cannot suspend your own account.")

        # The record and the effect commit together or not at all: an audit
        # trail that claims a suspension that never happened (or the reverse)
        # is worse than none.
        with transaction.atomic():
            record_admin_action(
                admin=request.user, action="USER_SUSPEND", target=target,
                reason=serializer.validated_data["reason"],
                before={"is_suspended": target.is_suspended},
                after={"is_suspended": True}, request=request,
            )

            target.is_suspended = True
            target.suspended_at = timezone.now()
            target.suspension_reason = serializer.validated_data["reason"]
            target.save(update_fields=["is_suspended", "suspended_at", "suspension_reason",
                                       "updated_at"])

            # Suspension has to take effect now. Without this the user keeps a
            # valid access token until it expires, and could keep spending.
            revoked = target.revoke_all_sessions()
        logger.info(
            "sessions_revoked",
            extra={"user_id": str(target.pk), "reason": "suspended", "tokens": revoked},
        )

        from apps.notifications.services import notify

        notify(
            target,
            event="ACCOUNT_SUSPENDED",
            title="Your account has been suspended",
            body="Your VerifyGH account has been suspended. Contact support if you believe "
                 "this is a mistake.",
            channels=("EMAIL", "IN_APP"),
        )
        return Response(AdminUserSerializer(self._get_user()).data)

    @action(detail=True, methods=["post"])
    def unsuspend(self, request, pk=None):
        self.required_permission = AdminPermission.USER_SUSPEND
        self.check_permissions(request)

        serializer = SuspendUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = self._get_user()

        with transaction.atomic():
            record_admin_action(
                admin=request.user, action="USER_UNSUSPEND", target=target,
                reason=serializer.validated_data["reason"],
                before={"is_suspended": target.is_suspended},
                after={"is_suspended": False}, request=request,
            )

            target.is_suspended = False
            target.suspended_at = None
            target.suspension_reason = ""
            target.save(update_fields=["is_suspended", "suspended_at", "suspension_reason",
                                       "updated_at"])
        return Response(AdminUserSerializer(self._get_user()).data)

    @action(detail=True, methods=["post"])
    def role(self, request, pk=None):
        """Assign a role. Super admins only; the rules live in accounts.staff."""
        self.required_permission = AdminPermission.USER_ROLE_CHANGE
        self.check_permissions(request)

        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff.change_role(
            target=self._get_user(), role=serializer.validated_data["role"],
            reason=serializer.validated_data["reason"], actor=request.user, request=request,
        )
        return Response(AdminUserSerializer(self._get_user()).data)

    @action(detail=False, methods=["post"])
    def invite(self, request):
        """Create a staff account; its owner chooses the password from an email."""
        self.required_permission = AdminPermission.USER_ROLE_CHANGE
        self.check_permissions(request)

        serializer = InviteStaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, delivered = staff.invite_staff(**serializer.validated_data, actor=request.user,
                                             request=request)
        data = AdminUserSerializer(User.objects.select_related("wallet").get(pk=user.pk)).data
        return Response({**data, "invite_sent": delivered}, status=201)

    @action(detail=True, methods=["post"], url_path="resend-invite")
    def resend_invite(self, request, pk=None):
        self.required_permission = AdminPermission.USER_ROLE_CHANGE
        self.check_permissions(request)

        target = self._get_user()
        delivered = staff.send_invite(target, actor=request.user, request=request)
        if not delivered:
            raise Conflict("The email provider didn't accept the invitation. Try again shortly.",
                           code="EMAIL_NOT_SENT")
        return Response({"detail": f"Invitation sent to {target.email}."})

    @action(detail=True, methods=["post"], url_path="change-email")
    def change_email(self, request, pk=None):
        """Correct an address the user mistyped. Unverified addresses only."""
        from apps.accounts.services import admin_change_unverified_email

        self.required_permission = AdminPermission.USER_EMAIL_CHANGE
        self.check_permissions(request)

        serializer = ChangeEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = self._get_user()

        if target.role in (Role.ADMIN, Role.SUPER_ADMIN) and request.user.role != Role.SUPER_ADMIN:
            raise Conflict("Only a super admin can change another admin's email.")
        if target.pk == request.user.pk:
            raise ValidationFailed("You cannot change your own email here.")

        admin_change_unverified_email(
            user=target, new_email=serializer.validated_data["new_email"],
            reason=serializer.validated_data["reason"], actor=request.user, request=request,
        )
        return Response(AdminUserSerializer(self._get_user()).data)

    @action(detail=True, methods=["post"], url_path="wallet-adjustment")
    def wallet_adjustment(self, request, pk=None):
        """Move a user's balance, with a mandatory reason and a ledger entry.

        There is no code path anywhere in this project that changes a balance
        without writing a ledger row; this endpoint is no exception.
        """
        self.required_permission = AdminPermission.WALLET_ADJUST
        self.check_permissions(request)

        serializer = WalletAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = self._get_user()
        wallet = get_or_create_wallet(target)

        direction = (
            LedgerDirection.CREDIT
            if serializer.validated_data["direction"] == "CREDIT"
            else LedgerDirection.DEBIT
        )

        # A double-submitted form must not move money twice. The console sends
        # an X-Idempotency-Key per form submission; without one, each call is new.
        client_key = str(request.headers.get("X-Idempotency-Key", "")).strip()[:64]
        idempotency_key = f"adjust:{request.user.pk}:{client_key or generate()}"

        # The ledger entry and its admin record commit together. Previously the
        # record was written first, so a refused debit (insufficient funds)
        # left an audit row describing an adjustment that never happened.
        with transaction.atomic():
            entry = adjust(
                wallet=wallet,
                amount=serializer.validated_data["amount"],
                direction=direction,
                idempotency_key=idempotency_key,
                reason=serializer.validated_data["reason"],
                admin=request.user,
            )
            already_recorded = AdminAction.objects.filter(
                action="WALLET_ADJUST", target_id=str(wallet.pk),
                after__ledger_reference=entry.reference,
            ).exists()
            if not already_recorded:
                record_admin_action(
                    admin=request.user, action="WALLET_ADJUST", target=wallet,
                    reason=serializer.validated_data["reason"],
                    before={"balance": str(entry.balance_before)},
                    after={
                        "balance": str(entry.balance_after),
                        "amount": str(serializer.validated_data["amount"]),
                        "direction": direction,
                        "ledger_reference": entry.reference,
                    },
                    request=request,
                )

        return Response(
            {
                "entry": LedgerEntrySerializer(entry).data,
                "user": AdminUserSerializer(self._get_user()).data,
            }
        )

    @action(detail=True, methods=["get"])
    def orders(self, request, pk=None):
        queryset = Order.objects.select_related("service", "country", "provider").filter(
            user_id=pk
        ).order_by("-created_at")[:100]
        return Response(AdminOrderSerializer(queryset, many=True).data)

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        self.required_permission = AdminPermission.WALLET_VIEW
        self.check_permissions(request)
        queryset = WalletLedgerEntry.objects.filter(wallet__user_id=pk).order_by(
            "-created_at"
        )[:100]
        return Response(LedgerEntrySerializer(queryset, many=True).data)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        logins = LoginAttempt.objects.filter(user_id=pk).order_by("-created_at")[:50]
        flags = SuspiciousActivity.objects.filter(user_id=pk).order_by("-created_at")[:50]
        audit = AuditLog.objects.filter(actor_id=pk).order_by("-created_at")[:50]
        wallet = get_or_create_wallet(self._get_user())
        return Response(
            {
                "logins": [
                    {
                        "successful": entry.successful,
                        "ip_address": entry.ip_address,
                        "failure_reason": entry.failure_reason,
                        "created_at": entry.created_at,
                    }
                    for entry in logins
                ],
                "flags": SuspiciousActivitySerializer(flags, many=True).data,
                "audit": AuditLogSerializer(audit, many=True).data,
                "wallet_integrity": verify_wallet_integrity(wallet),
            }
        )


# ---------------------------------------------------------------------------
# Orders, refunds, payments
# ---------------------------------------------------------------------------


class AdminOrderViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    serializer_class = AdminOrderSerializer
    required_permission = AdminPermission.ORDER_VIEW
    lookup_field = "reference"

    def get_queryset(self):
        queryset = Order.objects.select_related("user", "service", "country", "provider")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(user__email__icontains=search)
                | Q(provider_order_id__icontains=search)
                | Q(phone_number__icontains=search)
            )
        return queryset.order_by("-created_at")

    def _get_order(self) -> Order:
        order = self.get_queryset().filter(reference=self.kwargs["reference"]).first()
        if order is None:
            raise NotFound("We could not find that order.")
        return order

    @action(detail=True, methods=["get"])
    def timeline(self, request, reference=None):
        order = self._get_order()
        return Response(
            [
                {
                    "status": event.status,
                    "label": event.label,
                    "detail": event.detail,
                    "is_system": event.is_system,
                    "actor": event.actor.email if event.actor else None,
                    "created_at": event.created_at,
                }
                for event in order.events.all()
            ]
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        """Cancel upstream, where the provider allows it.

        We ask the provider; we never force a local state that contradicts what
        the provider believes.
        """
        self.required_permission = AdminPermission.ORDER_CANCEL
        self.check_permissions(request)

        serializer = SuspendUserSerializer(data=request.data)  # reuse: {"reason": ...}
        serializer.is_valid(raise_exception=True)
        order = self._get_order()

        before = {"status": order.status}
        # Recorded only once the cancellation has happened: the service raises
        # when the provider or the state machine refuses.
        order = cancel_order_service(
            order, actor=request.user, reason=serializer.validated_data["reason"]
        )
        record_admin_action(
            admin=request.user, action="ORDER_CANCEL", target=order,
            reason=serializer.validated_data["reason"],
            before=before, after={"status": order.status}, request=request,
        )
        return Response(AdminOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def refund(self, request, reference=None):
        self.required_permission = AdminPermission.ORDER_REFUND
        self.check_permissions(request)

        serializer = IssueRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self._get_order()

        if order.refund_status == "COMPLETED":
            raise Conflict("This order has already been refunded.")

        amount = serializer.validated_data.get("amount") or order.price
        if amount > order.price:
            raise ValidationFailed("A refund cannot exceed the order amount.")

        before = {"status": order.status, "refund_status": order.refund_status}
        order = issue_refund(
            order,
            reason=RefundReason.ADMIN_GOODWILL,
            amount=amount,
            actor=request.user,
            note=serializer.validated_data["reason"],
            automatic=False,
        )
        # issue_refund declines some orders (a completed one, for instance) by
        # returning them unchanged. Answering 200 there told the admin a refund
        # had been made when none had.
        if order.refund_status != "COMPLETED":
            raise Conflict("This order cannot be refunded. A completed order delivered the "
                           "service the user paid for.")
        record_admin_action(
            admin=request.user, action="ORDER_REFUND", target=order,
            reason=serializer.validated_data["reason"],
            before=before,
            after={"amount": str(amount), "refund_status": order.refund_status},
            request=request,
        )
        return Response(AdminOrderSerializer(order).data)


class AdminRefundViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AdminRefundSerializer
    required_permission = AdminPermission.ORDER_VIEW

    def get_queryset(self):
        return Refund.objects.select_related("order", "issued_by").order_by("-created_at")


class AdminPaymentViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = AdminPaymentSerializer
    required_permission = AdminPermission.PAYMENT_VIEW
    lookup_field = "reference"

    def get_serializer_class(self):
        # The list stays light; one payment gets the full diagnostic picture.
        if self.action == "retrieve":
            return AdminPaymentDetailSerializer
        return AdminPaymentSerializer

    def get_queryset(self):
        queryset = Payment.objects.select_related("user")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(user__email__icontains=search)
                | Q(provider_reference__icontains=search)
            )
        return queryset.order_by("-created_at")


# ---------------------------------------------------------------------------
# Catalog and pricing
# ---------------------------------------------------------------------------


def _audited_update(request, serializer, action: str):
    """Save a catalog edit and record every field it changed, in one transaction.

    The old per-view records listed only is_enabled, so an edit to a name,
    description or TTL left no trace of what it had been.
    """
    instance = serializer.instance
    fields = list(serializer.validated_data)
    before = {field: _plain(getattr(instance, field, None)) for field in fields}
    with transaction.atomic():
        saved = serializer.save()
        after = {field: _plain(getattr(saved, field, None)) for field in fields}
        changed = [field for field in fields if before[field] != after[field]]
        record_admin_action(
            admin=request.user, action=action, target=saved,
            reason=str(request.data.get("reason", "") or "Catalog update")[:500],
            before={field: before[field] for field in changed},
            after={field: after[field] for field in changed},
            request=request,
        )
    _invalidate_marketplace()


def _plain(value):
    return value if value is None or isinstance(value, bool | int | str) else str(value)


class AdminServiceViewSet(AdminBase, mixins.ListModelMixin, mixins.UpdateModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = AdminServiceSerializer
    required_permission = AdminPermission.CATALOG_MANAGE
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        from apps.catalog.marketplace import marketplace_country_codes

        return Service.objects.defer("logo_data").annotate(
            # Offerings customers can actually be sold: the services whose
            # branding matters, and the ones a missing logo is worth flagging.
            marketplace_offerings=Count(
                "offerings",
                filter=Q(offerings__country__code__in=marketplace_country_codes()),
                distinct=True,
            ),
            offering_count=Count("offerings", distinct=True),
            available_count=Count(
                "offerings", filter=Q(offerings__is_available=True), distinct=True
            ),
        ).order_by("display_order", "name")

    def perform_update(self, serializer):
        _audited_update(self.request, serializer, "SERVICE_UPDATE")

    @action(detail=True, methods=["post", "delete"], url_path="logo")
    def logo(self, request, slug=None):
        """Upload a replacement logo (POST, multipart `file`) or remove it (DELETE).

        Removing an uploaded logo goes back to the bundled one, if there is
        one. To show no logo at all, set icon_url to "" instead.
        """
        from apps.catalog.logos import validate_logo
        from apps.catalog.presentation import bundled_icon_url

        service = Service.objects.filter(slug=slug).first()
        if service is None:
            raise NotFound("We could not find that service.")
        before = {"icon_url": service.icon_url}

        if request.method == "POST":
            upload = request.FILES.get("file")
            data = upload.read() if upload else b""
            content_type = validate_logo(data)
            now = timezone.now()
            url = request.build_absolute_uri(f"/api/v1/service-logos/{service.slug}/")
            fields = {
                "logo_data": data,
                "logo_content_type": content_type,
                "logo_updated_at": now,
                "icon_url": f"{url}?v={int(now.timestamp())}",
            }
            action_name, default_reason = "SERVICE_LOGO_UPLOAD", "Service logo uploaded"
        else:
            fields = {
                "logo_data": None,
                "logo_content_type": "",
                "logo_updated_at": timezone.now(),
                "icon_url": bundled_icon_url(service.slug, service.name),
            }
            action_name, default_reason = "SERVICE_LOGO_REMOVE", "Service logo removed"

        with transaction.atomic():
            Service.objects.filter(pk=service.pk).update(**fields)
            record_admin_action(
                admin=request.user, action=action_name, target=service,
                reason=str(request.data.get("reason", "") or default_reason)[:500],
                before=before, after={"icon_url": fields["icon_url"],
                                      "content_type": fields["logo_content_type"]},
                request=request,
            )
        _invalidate_marketplace()
        service = self.get_queryset().get(pk=service.pk)
        return Response(AdminServiceSerializer(service).data)

    # -- Official brand logos (apps/catalog/brand_logos.py) -----------------

    LOGO_QUEUE_PAGE = 20

    @action(detail=False, methods=["get"], url_path="logo-queue")
    def logo_queue(self, request):
        """Services on sale that still show the generic tile and no one has decided."""
        from apps.catalog import brand_logos

        rows = self.get_queryset().filter(
            icon_url="", logo_data__isnull=True, logo_reviewed_at__isnull=True,
            marketplace_offerings__gt=0,
        )
        search = str(request.query_params.get("search") or "").strip()[:80]
        if search:
            rows = rows.filter(Q(name__icontains=search) | Q(slug__icontains=search))
        total = rows.count()
        try:
            page = max(int(request.query_params.get("page") or 1), 1)
        except ValueError:
            page = 1
        size = self.LOGO_QUEUE_PAGE
        chunk = rows.order_by("-is_popular", "popular_rank", "name")[(page - 1) * size:page * size]
        return Response({
            "configured": brand_logos.is_configured(),
            "count": total,
            "page": page,
            "pages": max((total + size - 1) // size, 1),
            "results": [{"slug": s.slug, "name": s.name, "category": s.category,
                         "is_popular": s.is_popular} for s in chunk],
        })

    @action(detail=True, methods=["get"], url_path="logo-candidates")
    def logo_candidates(self, request, slug=None):
        """Brands Brandfetch knows by this service's name (or `q`), searched live."""
        from apps.catalog import brand_logos

        service = Service.objects.defer("logo_data").filter(slug=slug).first()
        if service is None:
            raise NotFound("We could not find that service.")
        query = str(request.query_params.get("q") or service.name).strip()[:80]
        return Response({"query": query,
                         "results": [c.as_dict() for c in brand_logos.search(query)]})

    @action(detail=True, methods=["post", "delete"], url_path="brand-logo")
    def brand_logo(self, request, slug=None):
        """Decide a service's logo from the queue.

        POST {"domain": "venmo.com"}: use that brand's official logo.
        POST {"none": true}: no official logo found - leave the generic tile.
        DELETE: undo either, and put the service back in the queue.
        """
        from apps.catalog import brand_logos
        from apps.catalog.presentation import bundled_icon_url

        service = Service.objects.defer("logo_data").filter(slug=slug).first()
        if service is None:
            raise NotFound("We could not find that service.")
        if Service.objects.filter(pk=service.pk, logo_data__isnull=False).exists():
            raise Conflict("This service has an uploaded logo. Remove the upload first.")
        before = {"icon_url": service.icon_url, "logo_domain": service.logo_domain}
        now = timezone.now()

        if request.method == "DELETE":
            fields = {"logo_domain": "", "logo_reviewed_at": None}
            if brand_logos.is_brand_logo_url(service.icon_url):
                fields["icon_url"] = bundled_icon_url(service.slug, service.name)
            action_name, default_reason = "SERVICE_LOGO_REOPEN", "Logo decision undone"
        elif request.data.get("none") is True:
            fields = {"logo_domain": "", "logo_reviewed_at": now}
            if brand_logos.is_brand_logo_url(service.icon_url):
                fields["icon_url"] = ""
            action_name, default_reason = "SERVICE_LOGO_NONE", "No official logo found"
        else:
            domain = brand_logos.clean_domain(str(request.data.get("domain") or ""))
            fields = {"logo_domain": domain, "icon_url": brand_logos.logo_url(domain),
                      "logo_reviewed_at": now}
            action_name, default_reason = "SERVICE_LOGO_BRAND", f"Matched to {domain}"

        with transaction.atomic():
            Service.objects.filter(pk=service.pk).update(**fields)
            record_admin_action(
                admin=request.user, action=action_name, target=service,
                reason=str(request.data.get("reason", "") or default_reason)[:500],
                before=before,
                after={"icon_url": fields.get("icon_url", service.icon_url),
                       "logo_domain": fields["logo_domain"]},
                request=request,
            )
        _invalidate_marketplace()
        service = self.get_queryset().get(pk=service.pk)
        return Response(AdminServiceSerializer(service).data)


class AdminCountryViewSet(AdminBase, mixins.ListModelMixin, mixins.UpdateModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = AdminCountrySerializer
    required_permission = AdminPermission.CATALOG_MANAGE
    lookup_field = "code"
    pagination_class = None

    def get_queryset(self):
        return Country.objects.order_by("display_order", "name")

    def perform_update(self, serializer):
        _audited_update(self.request, serializer, "COUNTRY_UPDATE")


class AdminOfferingViewSet(AdminBase, mixins.ListModelMixin, mixins.UpdateModelMixin,
                           viewsets.GenericViewSet):
    """Provider cost against customer price, per (service, country)."""

    serializer_class = AdminOfferingSerializer
    required_permission = AdminPermission.CATALOG_MANAGE

    def get_queryset(self):
        queryset = ProviderService.objects.select_related("provider", "service", "country")
        if self.request.query_params.get("marketplace") == "1":
            # Only what customers can actually be sold (US and CA today).
            from apps.catalog.marketplace import marketplace_country_codes

            queryset = queryset.filter(country__code__in=marketplace_country_codes())
        service = self.request.query_params.get("service")
        if service:
            queryset = queryset.filter(service__slug=service)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(service__name__icontains=search) | Q(service__slug__icontains=search)
            )
        country = self.request.query_params.get("country")
        if country:
            queryset = queryset.filter(country__code=country.upper())
        return queryset.order_by("service__name", "country__name")

    def perform_update(self, serializer):
        _audited_update(self.request, serializer, "OFFERING_UPDATE")

    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request):
        self.required_permission = AdminPermission.PROVIDER_MANAGE
        self.check_permissions(request)
        from apps.catalog.services import sync_catalog

        # Inside a web request (gunicorn times out at 60s), so a provider that
        # prices one call at a time gets a short budget; the scheduled sync
        # carries on from where this one stops.
        summary = sync_catalog(time_budget=20)
        record_admin_action(
            admin=request.user, action="CATALOG_SYNC", target=None,
            reason="Manual catalog sync", after=summary, request=request,
        )
        return Response(summary)


class AdminPricingRuleViewSet(AdminBase, viewsets.ModelViewSet):
    serializer_class = PricingRuleSerializer
    required_permission = AdminPermission.PRICING_MANAGE
    pagination_class = None

    def check_permissions(self, request):
        # Reading rules is part of seeing the pricing; changing them is not.
        from rest_framework.permissions import SAFE_METHODS

        self.required_permission = (AdminPermission.PRICING_VIEW
                                    if request.method in SAFE_METHODS or self.action == "preview"
                                    else AdminPermission.PRICING_MANAGE)
        super().check_permissions(request)
    queryset = PricingRule.objects.select_related("service", "country").order_by(
        "priority", "-created_at"
    )

    @transaction.atomic
    def perform_create(self, serializer):
        reason = _pricing_reason(self.request)
        _check_rule_against_policy(serializer)
        rule = serializer.save()
        record_admin_action(
            admin=self.request.user, action="PRICING_RULE_CREATE", target=rule,
            reason=reason, after=PricingRuleSerializer(rule).data, request=self.request,
        )
        _invalidate_marketplace()
        _reprice_after_commit(self.request, reason)

    @transaction.atomic
    def perform_update(self, serializer):
        reason = _pricing_reason(self.request)
        _check_rule_against_policy(serializer)
        before = PricingRuleSerializer(serializer.instance).data
        rule = serializer.save()
        record_admin_action(
            admin=self.request.user, action="PRICING_RULE_UPDATE", target=rule,
            reason=reason, before=before, after=PricingRuleSerializer(rule).data,
            request=self.request,
        )
        _invalidate_marketplace()
        _reprice_after_commit(self.request, reason)

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.is_global_default:
            raise Conflict(
                "The global default pricing rule cannot be deleted - without it nothing "
                "can be priced."
            )
        reason = _pricing_reason(self.request)
        record_admin_action(
            admin=self.request.user, action="PRICING_RULE_DELETE", target=instance,
            reason=reason, before=PricingRuleSerializer(instance).data, request=self.request,
        )
        instance.delete()
        _invalidate_marketplace()
        _reprice_after_commit(self.request, reason)

    @action(detail=False, methods=["post"])
    def preview(self, request):
        """Price an offering under proposed settings before saving them."""
        offering_id = request.data.get("offering_id")
        offering = ProviderService.objects.select_related(
            "provider", "service", "country"
        ).filter(pk=offering_id).first()
        if offering is None:
            raise NotFound("We could not find that offering.")

        from apps.pricing.engine import quote_for_offering

        rule = None
        if request.data.get("rule"):
            serializer = PricingRuleSerializer(data=request.data["rule"])
            serializer.is_valid(raise_exception=True)
            rule = PricingRule(**serializer.validated_data)

        quote = quote_for_offering(offering, rule=rule)
        return Response(quote.as_dict())


class AdminPriceChangeViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every change to a customer price: old, new, what caused it, who and why."""

    serializer_class = PriceChangeSerializer
    required_permission = AdminPermission.PRICING_VIEW

    def get_queryset(self):
        from apps.pricing.models import PriceChange

        queryset = PriceChange.objects.select_related("changed_by")
        params = self.request.query_params
        if params.get("country"):
            queryset = queryset.filter(country_code=params["country"].upper())
        if params.get("source"):
            queryset = queryset.filter(source=params["source"])
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(service_name__icontains=search)
        return queryset.order_by("-created_at")


class AdminExchangeRateViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ExchangeRateSerializer
    required_permission = AdminPermission.PRICING_MANAGE
    pagination_class = None

    def check_permissions(self, request):
        from rest_framework.permissions import SAFE_METHODS

        self.required_permission = (AdminPermission.PRICING_VIEW if request.method in SAFE_METHODS
                                    else AdminPermission.PRICING_MANAGE)
        super().check_permissions(request)

    def get_queryset(self):
        return ExchangeRate.objects.order_by("-fetched_at", "-id")[:50]

    @transaction.atomic
    def create(self, request):
        """Append a new rate. Existing rate rows are never edited."""
        serializer = ExchangeRateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if Decimal(data["rate"]) <= 0:
            raise ValidationFailed("The exchange rate must be greater than zero.")

        rate = record_rate(
            data["rate"],
            base=data.get("base_currency", "USD"),
            quote=data.get("quote_currency", "GHS"),
            source="manual",
            note=data.get("note", ""),
            actor=request.user,
        )
        record_admin_action(
            admin=request.user, action="EXCHANGE_RATE_SET", target=rate,
            reason=str(request.data.get("reason", "Manual FX update"))[:500]
            or "Manual FX update",
            after={"rate": str(rate.rate)}, request=request,
        )
        _invalidate_marketplace()
        return Response(ExchangeRateSerializer(rate).data, status=201)


# ---------------------------------------------------------------------------
# Audit and abuse
# ---------------------------------------------------------------------------


class AdminAuditViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer
    required_permission = AdminPermission.AUDIT_VIEW

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor")
        action_filter = self.request.query_params.get("action")
        if action_filter:
            queryset = queryset.filter(action__icontains=action_filter)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(actor_email__icontains=search) | Q(target_id__icontains=search)
            )
        return queryset.order_by("-created_at")


class AdminActionViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AdminActionSerializer
    required_permission = AdminPermission.AUDIT_VIEW

    def get_queryset(self):
        return AdminAction.objects.select_related("admin").order_by("-created_at")


class AdminFlagViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = SuspiciousActivitySerializer
    required_permission = AdminPermission.USER_VIEW

    def get_queryset(self):
        queryset = SuspiciousActivity.objects.select_related("user")
        if self.request.query_params.get("resolved") != "true":
            queryset = queryset.filter(resolved=False)
        level = self.request.query_params.get("level")
        if level:
            queryset = queryset.filter(level=level.upper())
        return queryset.order_by("-created_at")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def resolve(self, request, pk=None):
        # Support can see abuse signals, but dismissing one is a judgement that
        # hides it from everyone else - it needs the same role as suspending.
        self.required_permission = AdminPermission.USER_SUSPEND
        self.check_permissions(request)

        serializer = ResolveFlagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = resolve_flag(
            flag_id=pk, admin=request.user, note=serializer.validated_data["note"]
        )
        record_admin_action(
            admin=request.user, action="FLAG_RESOLVE", target=entry,
            reason=serializer.validated_data["note"], request=request,
        )
        return Response(SuspiciousActivitySerializer(entry).data)


class AdminMaintenanceView(AdminBase, APIView):
    """The "Pause site" button: pause buying, pause buying and top-ups, or reopen."""

    required_permission = AdminPermission.METRICS_VIEW

    def get(self, request):
        from apps.common import maintenance

        return Response(maintenance.report())

    def post(self, request):
        from apps.common import maintenance

        self.required_permission = AdminPermission.MAINTENANCE_MANAGE
        self.check_permissions(request)
        return Response(maintenance.set_mode(
            mode=request.data.get("mode"), reason=request.data.get("reason"),
            message=request.data.get("message"),
            expected_back_minutes=request.data.get("expected_back_minutes"),
            actor=request.user, request=request,
        ))


class AdminSystemHealthView(AdminBase, APIView):
    """Is the platform actually able to trade right now?"""

    required_permission = AdminPermission.METRICS_VIEW

    def get(self, request):
        from apps.catalog.models import Provider
        from apps.payments.registry import get_payment_provider
        from apps.pricing.rates import latest_rate_row
        from apps.verification.registry import get_provider

        verification = get_provider()
        payments = get_payment_provider()
        rate = latest_rate_row()
        # A switched-off provider is not called, not even to ask if it is up.
        verification_row = Provider.objects.filter(adapter_key=verification.key).first()
        verification_enabled = verification_row is None or verification_row.is_enabled

        return Response(
            {
                "verification_provider": {
                    "key": verification.key,
                    "healthy": verification.health_check() if verification_enabled else False,
                    "enabled": verification_enabled,
                    "configured": verification.is_configured,
                    "resale_authorized": bool(verification_row
                                              and verification_row.resale_authorized),
                    "is_mock": verification.key == "mock",
                },
                "payment_provider": {
                    "key": payments.key,
                    "healthy": payments.health_check(),
                    "is_mock": payments.key == "mock",
                },
                "exchange_rate": {
                    "configured": rate is not None,
                    "rate": str(rate.rate) if rate else None,
                    "fetched_at": rate.fetched_at if rate else None,
                    "source": rate.source if rate else None,
                },
                "pricing_rules": PricingRule.objects.filter(is_active=True).count(),
                "providers": [
                    {
                        "name": provider.name,
                        "adapter_key": provider.adapter_key,
                        "is_enabled": provider.is_enabled,
                        "last_synced_at": provider.last_synced_at,
                        "last_sync_error": provider.last_sync_error[:200],
                    }
                    for provider in Provider.objects.all()
                ],
                "unprocessed_webhooks": _unprocessed_webhooks(),
            }
        )


def _unprocessed_webhooks() -> int:
    from apps.payments.models import PaymentWebhookEvent

    return PaymentWebhookEvent.objects.filter(processed=False, signature_valid=True).count()


def _invalidate_marketplace() -> None:
    from django.core.cache import cache

    from apps.catalog import marketplace
    from apps.catalog.views import MARKETPLACE_CACHE_KEY

    cache.delete(MARKETPLACE_CACHE_KEY)
    marketplace.invalidate()


def _pricing_reason(request) -> str:
    """Price changes are financial records: each one needs a stated reason."""
    reason = str(request.data.get("reason", "") or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason for this pricing change (at least 5 characters).")
    return reason[:500]


def _check_rule_against_policy(serializer) -> None:
    """A rule edit that would push prices below an enforced minimum margin is refused."""
    from apps.pricing import services as pricing

    candidate = PricingRule(**{
        f.attname: getattr(serializer.instance, f.attname)
        for f in PricingRule._meta.concrete_fields
    }) if serializer.instance else PricingRule()
    for name, value in serializer.validated_data.items():
        setattr(candidate, name, value)
    rules = [r for r in PricingRule.objects.filter(is_active=True)
             if not serializer.instance or r.pk != serializer.instance.pk]
    if candidate.is_active:
        rules.append(candidate)
    offerings = pricing.listed_offerings()
    policy = PricingPolicy.get()
    pricing._enforce_minimum(pricing.simulate(offerings, rules=rules, policy=policy),
                             offerings, policy)


def _reprice_after_commit(request, reason: str) -> None:
    from apps.pricing.history import refresh_offering_prices
    from apps.pricing.models import PriceChangeSource

    user = request.user
    transaction.on_commit(lambda: refresh_offering_prices(
        source=PriceChangeSource.PRICING_RULE, reason=reason, actor=user,
    ))
