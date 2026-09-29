"""Signed callbacks from verification providers.

A callback is a prompt, never a source of truth. The adapter verifies its
signature and names the reservations it concerns; each matching order is then
read back through the provider's authenticated API by the ordinary poll. So a
forged or replayed callback can at most cause one extra, harmless poll - and
without a valid signature it causes nothing at all.
"""

from __future__ import annotations

import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import ServiceUnavailable
from apps.common.throttling import WebhookThrottle

logger = logging.getLogger("verifygh.provider.webhooks")


@method_decorator(csrf_exempt, name="dispatch")
class VerificationWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [WebhookThrottle]

    def post(self, request, provider_key: str):
        from apps.orders.models import ACTIVE_ORDER_STATUSES, Order
        from apps.orders.tasks import poll_order_task
        from apps.verification.registry import get_provider

        try:
            adapter = get_provider(provider_key)
        except ServiceUnavailable:
            adapter = None
        if adapter is None or not adapter.accepts_webhooks:
            # Absent rather than locked: a switched-off endpoint gives nothing
            # to probe.
            return Response({"status": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        headers = {key.lower(): value for key, value in request.headers.items()}
        reservation_ids = adapter.parse_webhook(request.body, headers)
        if reservation_ids is None:
            logger.warning("verification_webhook_bad_signature", extra={"provider": provider_key})
            return Response({"status": "rejected"}, status=status.HTTP_401_UNAUTHORIZED)

        orders = list(
            Order.objects.filter(
                provider__adapter_key=provider_key,
                provider_order_id__in=[rid for rid in reservation_ids if rid],
                status__in=ACTIVE_ORDER_STATUSES,
            ).values_list("id", flat=True)
        )
        for order_id in orders:
            try:
                poll_order_task.delay(str(order_id))
            except Exception:
                # The scheduled poll will get there; a callback is only a hint.
                logger.warning("verification_webhook_poll_unqueued",
                               extra={"provider": provider_key})
        logger.info("verification_webhook_received",
                    extra={"provider": provider_key, "orders": len(orders)})
        return Response({"status": "ok"})
