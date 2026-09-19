from __future__ import annotations

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import IsActiveUser
from apps.wallet.models import WalletLedgerEntry
from apps.wallet.serializers import LedgerEntrySerializer, WalletSerializer
from apps.wallet.services import get_or_create_wallet


class WalletViewSet(viewsets.ViewSet):
    """The signed-in user's own wallet. There is no lookup by id: a user can
    only ever address their own wallet."""

    permission_classes = [IsAuthenticated, IsActiveUser]

    def list(self, request):
        wallet = get_or_create_wallet(request.user)
        return Response(WalletSerializer(wallet).data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        from apps.orders.models import ACTIVE_ORDER_STATUSES, Order, OrderStatus
        from apps.wallet.models import LedgerEntryType

        wallet = get_or_create_wallet(request.user)
        today = timezone.localtime().date()

        orders = Order.objects.filter(user=request.user)
        spent_today = WalletLedgerEntry.objects.filter(
            wallet=wallet,
            entry_type=LedgerEntryType.PURCHASE,
            created_at__date=today,
        ).aggregate(total=Sum("amount"))["total"]

        return Response(
            {
                "wallet": WalletSerializer(wallet).data,
                "today_spending": str(spent_today or "0.00"),
                "active_orders": orders.filter(status__in=ACTIVE_ORDER_STATUSES).count(),
                "successful_orders": orders.filter(status=OrderStatus.COMPLETED).count(),
                "total_orders": orders.count(),
            }
        )


class TransactionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Wallet ledger entries for the signed-in user.

    The queryset is filtered by owner, so an object-level permission check is
    never the only thing between two users' transaction histories.
    """

    serializer_class = LedgerEntrySerializer
    permission_classes = [IsAuthenticated, IsActiveUser]
    filterset_fields = ["entry_type", "direction"]

    def get_queryset(self):
        queryset = WalletLedgerEntry.objects.filter(wallet__user=self.request.user)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) | Q(description__icontains=search)
            )
        return queryset.order_by("-created_at")
