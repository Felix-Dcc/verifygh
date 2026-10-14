from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.errors import NotFound
from apps.common.idempotency import from_request, normalise
from apps.common.permissions import IsActiveUser
from apps.common.throttling import RentalCreateThrottle
from apps.rentals import services
from apps.rentals.models import OPEN_RENTAL_STATUSES, Rental, RentalStatus
from apps.rentals.serializers import (
    CreateRentalSerializer,
    ExtendRentalSerializer,
    RentalDetailSerializer,
    RentalListSerializer,
)
from apps.rentals.tasks import fulfil_rental_task

logger = logging.getLogger("verifygh.rentals")

STATUS_FILTERS = {
    "active": list(OPEN_RENTAL_STATUSES),
    "ended": [RentalStatus.EXPIRED, RentalStatus.REFUNDED, RentalStatus.FAILED],
}


def _key(request, given: str | None) -> str:
    return normalise(given) or from_request(request)


class RentalViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                    viewsets.GenericViewSet):
    """A customer's rented numbers: buy, read the inbox, extend, cancel."""

    permission_classes = [IsAuthenticated, IsActiveUser]
    lookup_field = "reference"

    def get_queryset(self):
        queryset = (Rental.objects.select_related("service", "provider")
                    .filter(user=self.request.user)
                    .annotate(message_total=Count("messages")))
        wanted = self.request.query_params.get("filter")
        if wanted in STATUS_FILTERS:
            queryset = queryset.filter(status__in=STATUS_FILTERS[wanted])
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(reference__icontains=search)
                                       | Q(service__name__icontains=search)
                                       | Q(phone_number__icontains=search))
        return queryset.order_by("-created_at")

    def get_throttles(self):
        if self.action in ("create", "extend"):
            return [RentalCreateThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        return RentalListSerializer if self.action == "list" else RentalDetailSerializer

    def get_object(self) -> Rental:
        rental = self.get_queryset().filter(reference=self.kwargs["reference"]).first()
        if rental is None:
            raise NotFound("We could not find that rental.")
        return rental

    def _detail(self, rental: Rental, code=status.HTTP_200_OK) -> Response:
        rental = self.get_queryset().prefetch_related("extensions").get(pk=rental.pk)
        return Response(RentalDetailSerializer(rental, context={"request": self.request}).data,
                        status=code)

    # -- before buying -----------------------------------------------------

    @action(detail=False, methods=["get"])
    def services(self, request):
        """The apps a number can be rented for (besides "any app")."""
        provider = services.rental_provider()
        return Response({
            "services": [{"slug": service.slug, "name": service.name,
                          "icon_url": service.icon_url, "is_popular": service.is_popular}
                         for service in services.rentable_services(provider)],
            "durations": [{"days": days, "label": services.duration_label(days)}
                          for days in services.offered_days()],
        })

    @action(detail=False, methods=["get"])
    def options(self, request):
        """Prices for every rental length, for one app or "all"."""
        return Response(services.options(request.query_params.get("service", "")))

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        from apps.common.errors import APIError

        try:
            services.check_rental_eligibility(request.user)
        except APIError as exc:
            return Response({"eligible": False, "code": exc.code, "message": exc.message})
        return Response({"eligible": True, "code": "", "message": ""})

    # -- buying ------------------------------------------------------------

    def create(self, request):
        serializer = CreateRentalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rental = services.create_rental(
            user=request.user, service_key=data["service"], days=data["days"],
            expected_price=data.get("expected_price"),
            idempotency_key=_key(request, data.get("idempotency_key")), request=request,
        )
        if rental.status == RentalStatus.PENDING:
            transaction.on_commit(lambda: fulfil_rental_task.delay(str(rental.id)))
        return self._detail(rental, status.HTTP_201_CREATED)

    # -- the live rental -----------------------------------------------------

    def retrieve(self, request, reference=None):
        """The rental and its inbox, catching up with the provider as it is read.

        Bounded per rental: messages at most every LIVE_SYNC_SECONDS, the
        provider's cancel window every LIVE_REFRESH_SECONDS. The sweep covers
        rentals nobody is looking at.
        """
        rental = self.get_object()
        try:
            if rental.status == RentalStatus.PENDING and rental.provider_sale_id and \
                    cache.add(f"rental-live-fulfil:{rental.pk}", 1, timeout=5):
                rental = services.fulfil_rental(rental)
            if rental.status == RentalStatus.ACTIVE:
                if rental.can_refund and cache.add(f"rental-live-refresh:{rental.pk}", 1,
                                                   timeout=services.LIVE_REFRESH_SECONDS):
                    rental = services.refresh_rental(rental)
                due = cache.add(f"rental-live-sync:{rental.pk}", 1,
                                timeout=services.LIVE_SYNC_SECONDS)
                if due and services.sync_messages(rental) and rental.can_refund:
                    # A message usually closes the provider's refund window:
                    # show that now rather than at the next minute's read.
                    services.refresh_rental(rental)
        except Exception:
            logger.warning("rental_live_refresh_failed", extra={"rental": rental.reference})
        return self._detail(rental)

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        rental = services.cancel_rental(self.get_object(), actor=request.user, request=request)
        return self._detail(rental)

    @action(detail=True, methods=["get"], url_path="extension-quote")
    def extension_quote(self, request, reference=None):
        priced = services.extension_quote(self.get_object(), request.query_params.get("days"))
        return Response({"days": priced.days, "label": services.duration_label(priced.days),
                         "price": str(priced.price), "currency": "GHS"})

    @action(detail=True, methods=["post"])
    def extend(self, request, reference=None):
        serializer = ExtendRentalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rental = self.get_object()
        services.extend_rental(
            rental, user=request.user, days=data["days"],
            expected_price=data.get("expected_price"),
            idempotency_key=_key(request, data.get("idempotency_key")), request=request,
        )
        return self._detail(rental)
