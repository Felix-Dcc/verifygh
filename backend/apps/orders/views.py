from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.errors import NotFound
from apps.common.idempotency import from_request
from apps.common.permissions import IsActiveUser
from apps.common.throttling import IssueReportThrottle, OrderCreateThrottle
from apps.orders import services
from apps.orders.models import ACTIVE_ORDER_STATUSES, TERMINAL_ORDER_STATUSES, Order, OrderStatus
from apps.orders.serializers import (
    CreateOrderSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    QuoteSerializer,
)
from apps.orders.tasks import fulfil_order_task

logger = logging.getLogger("verifygh.orders")

#: Statuses where asking the provider again can still change something.
POLLABLE_STATUSES = {
    OrderStatus.PROCESSING,
    OrderStatus.NUMBER_ASSIGNED,
    OrderStatus.WAITING_FOR_CODE,
}

STATUS_FILTERS = {
    "active": list(ACTIVE_ORDER_STATUSES),
    "completed": [OrderStatus.COMPLETED],
    "failed": [OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED],
    "refunded": [OrderStatus.REFUNDED],
}


class OrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, IsActiveUser]
    lookup_field = "reference"

    def get_queryset(self):
        queryset = (
            Order.objects.select_related("service", "country", "provider")
            .filter(user=self.request.user)
        )

        status_filter = self.request.query_params.get("filter")
        if status_filter in STATUS_FILTERS:
            queryset = queryset.filter(status__in=STATUS_FILTERS[status_filter])

        explicit = self.request.query_params.get("status")
        if explicit:
            queryset = queryset.filter(status=explicit.upper())

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(service__name__icontains=search)
                | Q(phone_number__icontains=search)
            )

        return queryset.order_by("-created_at")

    def get_throttles(self):
        # Buying is the expensive action, so it gets its own tight bucket.
        if self.action == "create":
            return [OrderCreateThrottle()]
        if self.action == "report":
            return [IssueReportThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        return OrderDetailSerializer

    def get_object(self) -> Order:
        order = (
            self.get_queryset()
            .prefetch_related("events")
            .filter(reference=self.kwargs["reference"])
            .first()
        )
        if order is None:
            raise NotFound("We could not find that order.")
        return order

    # -- pre-purchase ----------------------------------------------------

    @action(detail=False, methods=["get"])
    def quote(self, request):
        """Server-side price for a (service, country) pair.

        The UI shows this, but the order endpoint prices independently - a quote
        is information, never an authorisation.
        """
        serializer = QuoteSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        priced = services.quote(
            serializer.validated_data["service"], serializer.validated_data["country"]
        )
        from apps.wallet.services import get_or_create_wallet

        wallet = get_or_create_wallet(request.user)
        priced["wallet_balance"] = str(wallet.balance)
        priced["sufficient_balance"] = wallet.balance >= Decimal(priced["price"])
        return Response(priced)

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        """Tell the UI up front what would block a purchase."""
        from apps.common.errors import APIError

        try:
            services.check_purchase_eligibility(request.user)
        except APIError as exc:
            return Response({"eligible": False, "code": exc.code, "message": exc.message})
        return Response({"eligible": True, "code": "", "message": ""})

    # -- purchase --------------------------------------------------------

    def create(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        idempotency_key = serializer.validated_data.get("idempotency_key") or from_request(request)

        order = services.create_order(
            user=request.user,
            service_slug=serializer.validated_data["service"],
            country_code=serializer.validated_data["country"],
            idempotency_key=idempotency_key,
            request=request,
        )

        # Talk to the provider after the money transaction has committed.
        if order.status == OrderStatus.PROCESSING:
            transaction.on_commit(lambda: fulfil_order_task.delay(str(order.id)))

        order.refresh_from_db()
        return Response(
            OrderDetailSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # -- live order ------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="status")
    def live_status(self, request, reference=None):
        """Lightweight polling endpoint for the active-order screen.

        Hits our own database only. The upstream provider is polled on our own
        schedule by Celery, never once per browser tick.
        """
        order = self.get_object()

        # Opportunistic refresh: if this order is genuinely waiting and we have
        # not asked the provider recently, ask now. Bounded by a per-order
        # cooldown so a user holding the screen open cannot turn into a stream
        # of upstream calls - the Celery sweep still covers users who close the
        # tab, and the provider rate limiter sits underneath both.
        if order.status in POLLABLE_STATUSES and order.provider_order_id:
            cooldown_key = f"order_poll:{order.pk}"
            if cache.add(cooldown_key, 1, timeout=settings.VERIFYGH["ORDER_POLL_SECONDS"]):
                try:
                    order = services.poll_order(order)
                except Exception:
                    logger.warning("inline_poll_failed", extra={"order": order.reference})

        return Response(
            {
                "reference": order.reference,
                "status": order.status,
                "phone_number": order.phone_number,
                "verification_code": (
                    order.verification_code if order.may_display_code else ""
                ),
                "code_display_allowed": order.may_display_code,
                "seconds_remaining": OrderDetailSerializer(
                    order, context={"request": request}
                ).get_seconds_remaining(order),
                "refund_status": order.refund_status,
                "failure_reason": order.failure_reason,
                "poll_interval_seconds": settings.VERIFYGH["ORDER_POLL_SECONDS"],
            }
        )

    @action(detail=True, methods=["post"])
    def reuse(self, request, reference=None):
        """Buy another code on this order's number, while the provider allows it."""
        order = services.reuse_number(user=request.user, original=self.get_object(),
                                      idempotency_key=from_request(request), request=request)
        if order.status == OrderStatus.PROCESSING:
            transaction.on_commit(lambda: fulfil_order_task.delay(str(order.id)))
        order.refresh_from_db()
        return Response(OrderDetailSerializer(order, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def complete(self, request, reference=None):
        order = services.complete_order(self.get_object(), actor=request.user)
        return Response(OrderDetailSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        order = services.cancel_order(
            self.get_object(),
            actor=request.user,
            reason=str(request.data.get("reason", ""))[:200],
        )
        return Response(OrderDetailSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def report(self, request, reference=None):
        """Report a problem with a delivered number.

        Opens a case for staff; never moves money by itself. A repeat report on
        the same order returns the existing case with 200 rather than 201.
        """
        from apps.numbers.serializers import CustomerIssueSerializer, ReportIssueSerializer
        from apps.numbers.services import report_issue

        serializer = ReportIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue, created = report_issue(
            self.get_object(), user=request.user, request=request, **serializer.validated_data
        )
        return Response(
            CustomerIssueSerializer(issue).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # -- summary ---------------------------------------------------------

    @action(detail=False, methods=["get"])
    def active(self, request):
        orders = (
            self.get_queryset()
            .filter(status__in=ACTIVE_ORDER_STATUSES)
            .exclude(status__in=TERMINAL_ORDER_STATUSES)[:10]
        )
        return Response(
            OrderListSerializer(orders, many=True, context={"request": request}).data
        )
