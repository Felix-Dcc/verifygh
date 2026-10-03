"""Staff side of number-quality reports.

Viewing needs ORDER_VIEW. Moving a case along without money (review, reject,
resolve) needs ISSUE_MANAGE. Anything that costs money - a refund, or a free
replacement number - needs ORDER_REFUND. Every action carries a written reason
and lands in the AdminAction log.
"""

from __future__ import annotations

from django.db.models import Q
from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import AdminPermission
from apps.adminapi.views import AdminBase
from apps.common.errors import NotFound
from apps.numbers import services
from apps.numbers.models import IssueEvidence, VerificationIssue
from apps.numbers.serializers import (
    AdminIssueActionSerializer,
    AdminIssueDetailSerializer,
    AdminIssueSerializer,
)


class AdminIssueViewSet(AdminBase, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    serializer_class = AdminIssueSerializer
    required_permission = AdminPermission.ORDER_VIEW
    lookup_field = "reference"

    def get_queryset(self):
        queryset = VerificationIssue.objects.select_related(
            "order__provider", "order__service", "order__country", "user", "number_record",
            "resolved_by", "replacement_order",
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("reason"):
            queryset = queryset.filter(reason=params["reason"])
        if params.get("needs_review") == "1":
            queryset = queryset.filter(needs_review=True)
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) | Q(order__reference__icontains=search)
                | Q(user__email__icontains=search)
            )
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return AdminIssueSerializer
        return AdminIssueDetailSerializer

    def _issue(self) -> VerificationIssue:
        issue = self.get_queryset().filter(reference=self.kwargs["reference"]).first()
        if issue is None:
            raise NotFound("We could not find that report.")
        return issue

    def _act(self, request, permission: str, fn):
        self.required_permission = permission
        self.check_permissions(request)
        serializer = AdminIssueActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = fn(self._issue(), admin=request.user,
                   reason=serializer.validated_data["reason"], request=request)
        return Response(AdminIssueDetailSerializer(self._issue()).data)

    @action(detail=True, methods=["post"])
    def review(self, request, reference=None):
        return self._act(request, AdminPermission.ISSUE_MANAGE, services.start_review)

    @action(detail=True, methods=["post"])
    def refund(self, request, reference=None):
        return self._act(request, AdminPermission.ORDER_REFUND, services.approve_refund)

    @action(detail=True, methods=["post"])
    def replace(self, request, reference=None):
        return self._act(request, AdminPermission.ORDER_REFUND, services.approve_replacement)

    @action(detail=True, methods=["post"])
    def reject(self, request, reference=None):
        return self._act(request, AdminPermission.ISSUE_MANAGE, services.reject_claim)

    @action(detail=True, methods=["post"])
    def resolve(self, request, reference=None):
        return self._act(request, AdminPermission.ISSUE_MANAGE, services.mark_resolved)

    # -- a report the provider is reviewing ---------------------------------

    @action(detail=True, methods=["post"], url_path="ticket-filed")
    def ticket_filed(self, request, reference=None):
        """Record the support ticket staff opened with the provider."""
        return self._act(request, AdminPermission.ISSUE_MANAGE, services.mark_ticket_filed)

    @action(detail=True, methods=["post"], url_path="provider-refunded")
    def provider_refunded(self, request, reference=None):
        """The provider refunded through its support: refund the customer."""
        return self._act(request, AdminPermission.ORDER_REFUND,
                         services.settle_provider_refund)

    @action(detail=True, methods=["post"], url_path="provider-declined")
    def provider_declined(self, request, reference=None):
        """The provider declined; the reason is its reply, shown to the customer."""
        return self._act(request, AdminPermission.ISSUE_MANAGE, services.provider_declined)

    @action(detail=True, methods=["get"], url_path=r"evidence/(?P<evidence_id>[0-9a-f-]{36})")
    def evidence(self, request, reference=None, evidence_id=None):
        """A customer's screenshot, for staff only.

        Served with headers that stop a browser treating it as anything but an
        image: the type was checked from the bytes on upload, and nosniff plus
        a locked-down CSP keep it that way.
        """
        item = IssueEvidence.objects.filter(
            pk=evidence_id, issue__reference=self.kwargs["reference"]).first()
        if item is None:
            raise NotFound("We could not find that screenshot.")
        response = HttpResponse(bytes(item.data), content_type=item.content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-store"
        response["Content-Disposition"] = (
            f'inline; filename="{self.kwargs["reference"]}-{str(item.pk)[:8]}'
            f'.{item.content_type.split("/")[-1]}"')
        return response


class AdminIssueMetricsView(AdminBase, APIView):
    required_permission = AdminPermission.METRICS_VIEW

    def get(self, request):
        try:
            days = max(1, min(365, int(request.query_params.get("days", 30))))
        except ValueError:
            days = 30
        return Response(services.metrics(days))
