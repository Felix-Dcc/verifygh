"""Rentals in the admin console: read-only, like the orders list."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.rentals.models import DELIVERED_RENTAL_STATUSES, Rental, RentalStatus
from apps.rentals.serializers import AdminRentalSerializer, RentalMessageSerializer


class AdminRentalViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = AdminRentalSerializer
    required_permission = AdminPermission.ORDER_VIEW
    lookup_field = "reference"

    def get_queryset(self):
        queryset = (Rental.objects.select_related("user", "service", "provider")
                    .annotate(message_total=Count("messages")))
        wanted = self.request.query_params.get("status")
        if wanted:
            queryset = queryset.filter(status=wanted.upper())
        search = (self.request.query_params.get("search")
                  or self.request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) | Q(user__email__icontains=search)
                | Q(phone_number__icontains=search) | Q(provider_rental_id__icontains=search)
                | Q(provider_service_name__icontains=search))
        return queryset.order_by("-created_at")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts and takings: what customers paid for rentals they received."""
        since = timezone.now() - timedelta(days=30)
        delivered = Rental.objects.filter(status__in=DELIVERED_RENTAL_STATUSES)
        takings = delivered.aggregate(total=Sum("price"))["total"] or Decimal("0.00")
        recent = delivered.filter(created_at__gte=since).aggregate(
            total=Sum("price"))["total"] or Decimal("0.00")
        return Response({
            "active": Rental.objects.filter(status=RentalStatus.ACTIVE).count(),
            "pending": Rental.objects.filter(status=RentalStatus.PENDING).count(),
            "ended": Rental.objects.filter(status=RentalStatus.EXPIRED).count(),
            "refunded_or_failed": Rental.objects.filter(
                status__in=[RentalStatus.REFUNDED, RentalStatus.FAILED]).count(),
            "takings": str(takings),
            "takings_30d": str(recent),
        })

    @action(detail=True, methods=["get"])
    def messages(self, request, reference=None):
        """Message metadata for support. The text and codes are the customer's."""
        rental = self.get_queryset().filter(reference=reference).first()
        if rental is None:
            from apps.common.errors import NotFound

            raise NotFound("We could not find that rental.")
        data = RentalMessageSerializer(rental.messages.all()[:200], many=True).data
        for row in data:
            row["body"] = ""
            row["code"] = ""
        return Response(data)
