from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import NETWORK_PREFIXES, MomoNetwork
from apps.common.errors import NotFound
from apps.common.middleware import get_client_ip
from apps.common.permissions import IsActiveUser
from apps.common.throttling import DepositThrottle, OtpSubmitThrottle, WebhookThrottle
from apps.payments.models import Payment, PaymentStatus
from apps.payments.registry import get_payment_provider, webhook_providers
from apps.payments.serializers import (
    DepositSerializer,
    PaymentSerializer,
    SubmitOtpSerializer,
)
from apps.payments.services import (
    deposits_blocked_reason,
    initiate_deposit,
    process_webhook,
    reconcile_payment,
    submit_deposit_otp,
)

logger = logging.getLogger("verifygh.payments")


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, IsActiveUser]
    filterset_fields = ["status", "network"]
    lookup_field = "reference"

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user).order_by("-created_at")

    @action(detail=False, methods=["post"], throttle_classes=[DepositThrottle])
    def deposit(self, request):
        serializer = DepositSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = initiate_deposit(
            user=request.user,
            amount=data["amount"],
            phone=data["phone"],
            network=data["network"],
            request=request,
            network_source=data.get("network_source", ""),
            detected_network=data.get("detected_network", ""),
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="otp",
            throttle_classes=[OtpSubmitThrottle])
    def submit_otp(self, request, reference=None):
        """Hand the provider a one-time code the customer just received.

        The code never touches the browser's storage and is never returned in
        the response. Ownership, state, expiry and attempt count are all checked
        in the service, under a row lock - none of it is decided here.
        """
        serializer = SubmitOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = submit_deposit_otp(
            user=request.user,
            reference=reference,
            otp=serializer.validated_data["otp"],
        )
        return Response(PaymentSerializer(payment).data)

    @action(detail=True, methods=["post"])
    def refresh(self, request, reference=None):
        """Ask the provider directly what happened to this payment.

        The waiting screen polls this, so a payment the provider has already
        failed says so within seconds - no callback arrived for the failed
        Mobile Money charges seen so far, and the scheduled sweep only runs
        every 15 minutes.
        It never *sets* a status, it only asks the provider and applies the
        provider's answer. The provider is asked at most once per
        PROVIDER_CHECK_SECONDS per payment, however many tabs are polling; in
        between, this answers from our own record.
        """
        payment = self.get_queryset().filter(reference=reference).first()
        if payment is None:
            raise NotFound("We could not find that payment.")
        # While a one-time code is awaited the customer must act; the provider
        # has nothing to tell us yet.
        waiting_for_code = payment.status == PaymentStatus.OTP_REQUIRED
        if not payment.is_terminal and not waiting_for_code and _provider_check_due(payment):
            payment = reconcile_payment(payment)
        return Response(PaymentSerializer(payment).data)


#: The least time between two provider look-ups for one payment.
PROVIDER_CHECK_SECONDS = 4


def _provider_check_due(payment: Payment) -> bool:
    """True when this payment's provider look-up is not on cooldown.

    Fails closed: with the cache unreachable, the provider is not asked (the
    scheduled sweep still settles the payment), rather than letting a polling
    client turn into unlimited calls to Paystack.
    """
    try:
        return cache.add(f"payment-provider-check:{payment.pk}", 1, PROVIDER_CHECK_SECONDS)
    except Exception:
        logger.warning("payment_check_cooldown_unavailable",
                       extra={"reference": payment.reference})
        return False


class PaymentOptionsView(APIView):
    """Supported MoMo networks and deposit limits, served dynamically."""

    permission_classes = [AllowAny]

    def get(self, request):
        provider = get_payment_provider()
        supported = set(provider.supported_networks)
        # So the deposit screen can explain itself instead of offering a form
        # that is guaranteed to fail on submit.
        blocked = deposits_blocked_reason()
        networks = [
            {
                "value": str(value),
                "label": label,
                "prefixes": list(NETWORK_PREFIXES.get(value, ())),
            }
            for value, label in MomoNetwork.choices
            if value in supported
        ]
        return Response(
            {
                "networks": networks,
                "currency": "GHS",
                "min_deposit": str(settings.VERIFYGH["MIN_DEPOSIT"]),
                "max_deposit": str(settings.VERIFYGH["MAX_DEPOSIT"]),
                "max_balance": str(settings.VERIFYGH["MAX_WALLET_BALANCE"]),
                "quick_amounts": ["10.00", "20.00", "50.00", "100.00", "200.00"],
                "deposits_enabled": not blocked,
                "deposits_disabled_reason": blocked,
                "fee_note": provider.customer_fee_note,
            }
        )


class WebhookView(APIView):
    """Provider callbacks.

    Unauthenticated by necessity (the provider has no session) but never
    untrusted: the signature is verified against the raw body before anything
    is read out of it.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [WebhookThrottle]

    @csrf_exempt
    def post(self, request, provider_key: str):
        if provider_key not in webhook_providers():
            # 404, not 401: an endpoint that is switched off should look absent,
            # not like a door with a lock to try.
            logger.warning("webhook_provider_not_enabled", extra={"provider": provider_key})
            return Response({"status": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        raw_body = request.body
        # Lowercase keys, so adapters look headers up the way HTTP defines
        # them: case-insensitively. dict(request.headers) keeps Django's
        # Title-Case keys, which silently broke Paystack's signature lookup.
        headers = {key.lower(): value for key, value in request.headers.items()}

        result = process_webhook(
            provider_key=provider_key,
            raw_body=raw_body,
            headers=headers,
            remote_ip=get_client_ip(request) or None,
        )

        if result.status == "invalid_signature":
            # 401, and deliberately no detail about why.
            return Response({"status": "rejected"}, status=status.HTTP_401_UNAUTHORIZED)

        if result.status == "unrecorded":
            # We could not even store it. Answer 5xx so the provider tries again
            # - acknowledging it would be losing it.
            return Response(result.as_dict(), status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Everything safely recorded answers 200, including duplicates and
        # stored-but-unparseable events: a retry of either cannot help.
        return Response(result.as_dict(), status=status.HTTP_200_OK)
