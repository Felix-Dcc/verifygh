"""Admin > Manual top-ups: the review queue for manual MoMo transfers."""

from __future__ import annotations

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.common.errors import NotFound
from apps.payments import manual
from apps.payments.models import Payment, PaymentEvidence, PaymentStatus


def _row(payment: Payment) -> dict:
    meta = payment.metadata or {}
    return {
        "reference": payment.reference,
        "status": payment.status,
        "amount": str(payment.amount),
        "claimed_amount": meta.get("claimed_amount", str(payment.amount)),
        "received_amount": meta.get("received_amount"),
        "user_email": payment.user.email,
        # Staff match this against the wallet's history, so it is shown whole.
        "sender_phone": payment.phone,
        "network": payment.network,
        "transaction_id": meta.get("sender_transaction_id", ""),
        "receipt_id": payment.provider_reference,
        "failure_reason": payment.failure_reason,
        "claimed_at": meta.get("claimed_at"),
        "created_at": payment.created_at.isoformat(),
        "completed_at": payment.completed_at.isoformat() if payment.completed_at else None,
        "evidence": [{"id": str(item.pk), "content_type": item.content_type, "size": item.size}
                     for item in payment.evidence.all()],
    }


class ManualDepositsView(AdminBase, APIView):
    required_permission = AdminPermission.PAYMENT_VIEW

    def get(self, request):
        base = (Payment.objects.filter(provider=manual.KEY).select_related("user")
                .prefetch_related("evidence"))
        waiting = base.filter(status=PaymentStatus.PROCESSING).order_by("updated_at")
        decided = base.filter(status__in=[PaymentStatus.SUCCESS, PaymentStatus.FAILED]) \
            .order_by("-completed_at")[:30]
        return Response({
            "settings": manual.details(),
            "enabled": manual.is_enabled(),
            "reject_reasons": list(manual.REJECT_REASONS),
            "waiting": [_row(p) for p in waiting],
            "decided": [_row(p) for p in decided],
        })


class ManualDepositSettingsView(AdminBase, APIView):
    required_permission = AdminPermission.WALLET_ADJUST

    def post(self, request):
        return Response(manual.set_enabled(enabled=request.data.get("enabled"),
                                           reason=request.data.get("reason"),
                                           actor=request.user, request=request))


class ManualDepositApproveView(AdminBase, APIView):
    required_permission = AdminPermission.WALLET_ADJUST

    def post(self, request, reference: str):
        payment = manual.approve(reference=reference,
                                 amount_received=request.data.get("amount_received"),
                                 receipt_id=request.data.get("receipt_id", ""),
                                 actor=request.user, request=request)
        return Response(_row(payment))


class ManualDepositRejectView(AdminBase, APIView):
    required_permission = AdminPermission.WALLET_ADJUST

    def post(self, request, reference: str):
        payment = manual.reject(reference=reference, reason=request.data.get("reason", ""),
                                actor=request.user, request=request)
        return Response(_row(payment))


class ManualDepositEvidenceView(AdminBase, APIView):
    """A customer's screenshot, for staff only, served so it stays an image."""

    required_permission = AdminPermission.PAYMENT_VIEW

    def get(self, request, reference: str, evidence_id: str):
        item = PaymentEvidence.objects.filter(pk=evidence_id, payment__reference=reference,
                                              payment__provider=manual.KEY).first()
        if item is None:
            raise NotFound("We could not find that screenshot.")
        response = HttpResponse(bytes(item.data), content_type=item.content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-store"
        return response
