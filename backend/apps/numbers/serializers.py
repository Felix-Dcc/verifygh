from __future__ import annotations

from rest_framework import serializers

from apps.numbers import services
from apps.numbers.models import IssueReason, IssueStatus, NumberRecord, VerificationIssue

#: What the customer sees for each status. Staff notes stay internal - they are
#: written for colleagues, not for the customer.
CUSTOMER_STATUS_TEXT = {
    IssueStatus.OPEN: services.CUSTOMER_MESSAGE,
    IssueStatus.IN_REVIEW: "We're reviewing your report.",
    IssueStatus.AWAITING_PROVIDER: "We've sent your report and screenshot to our number "
                                   "provider. If they approve it, the full amount comes back "
                                   "to your wallet automatically.",
    IssueStatus.REFUNDED: "We confirmed the problem and refunded this order to your wallet.",
    IssueStatus.REPLACED: "We confirmed the problem and gave you a replacement number at no "
                          "charge.",
    IssueStatus.REJECTED: "We reviewed your report and could not confirm the number was "
                          "unusable. Contact support if you'd like us to look again.",
    IssueStatus.RESOLVED: "Your report is resolved.",
}


class ReportIssueSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=IssueReason.choices)
    details = serializers.CharField(required=False, allow_blank=True, max_length=500)
    #: The answer to "Did the service ask for an existing password instead of
    #: letting you create an account?" - required for NUMBER_ALREADY_LINKED.
    confirmed_existing_account = serializers.BooleanField(required=False, default=False)
    #: Screenshots supporting the claim; required where the provider reviews
    #: reports. Checked by their bytes in services.read_evidence.
    evidence = serializers.ListField(child=serializers.FileField(), required=False,
                                     allow_empty=True)


class CustomerIssueSerializer(serializers.ModelSerializer):
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    message = serializers.SerializerMethodField()
    replacement_order_reference = serializers.CharField(
        source="replacement_order.reference", default=None, read_only=True
    )

    class Meta:
        model = VerificationIssue
        fields = ["reference", "reason", "reason_label", "status", "status_label", "message",
                  "replacement_order_reference", "decision_due_at", "created_at"]
        read_only_fields = fields

    decision_due_at = serializers.DateTimeField(source="provider_decision_due_at",
                                                read_only=True)

    def get_message(self, obj) -> str:
        if obj.status == IssueStatus.REJECTED and obj.customer_reply:
            return ("Our number provider reviewed your report and did not approve a refund. "
                    f"Their reply: {obj.customer_reply}")
        return CUSTOMER_STATUS_TEXT.get(obj.status, "")


class AdminIssueSerializer(serializers.ModelSerializer):
    """The case list and detail. The full phone number never appears here."""

    order_reference = serializers.CharField(source="order.reference", read_only=True)
    order_status = serializers.CharField(source="order.status", read_only=True)
    customer_id = serializers.UUIDField(source="user.id", read_only=True)
    customer_email = serializers.EmailField(source="user.email", read_only=True)
    provider_name = serializers.CharField(source="order.provider.name", read_only=True)
    provider_key = serializers.CharField(source="order.provider.adapter_key", read_only=True)
    service_name = serializers.CharField(source="order.service.name", read_only=True)
    service_icon = serializers.CharField(source="order.service.icon_url", read_only=True)
    country_code = serializers.CharField(source="order.country.code", read_only=True)
    number_masked = serializers.SerializerMethodField()
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    resolved_by_email = serializers.EmailField(source="resolved_by.email", default=None,
                                               read_only=True)
    replacement_order_reference = serializers.CharField(
        source="replacement_order.reference", default=None, read_only=True
    )
    replacement_order_status = serializers.CharField(
        source="replacement_order.status", default=None, read_only=True
    )
    price = serializers.DecimalField(source="order.price", max_digits=12, decimal_places=2,
                                     read_only=True)
    refund = serializers.SerializerMethodField()

    class Meta:
        model = VerificationIssue
        fields = [
            "id", "reference", "order_reference", "order_status", "customer_id",
            "customer_email", "provider_name", "provider_key", "service_name", "service_icon",
            "country_code",
            "number_masked", "reason", "reason_label", "details", "status", "status_label",
            "qualifies", "qualification", "risk_flags", "needs_review", "resolution_note",
            "resolved_by_email", "resolved_at", "replacement_order_reference",
            "replacement_order_status", "provider_report", "price", "refund", "created_at",
            "provider_reported_at", "provider_decision_due_at", "provider_state",
            "provider_checked_at", "provider_ticket_reference", "provider_ticket_filed_at",
            "customer_reply", "evidence_count",
        ]
        read_only_fields = fields

    evidence_count = serializers.SerializerMethodField()

    def get_evidence_count(self, obj) -> int:
        return obj.evidence.count()

    def get_number_masked(self, obj) -> str:
        if obj.number_record_id:
            return obj.number_record.number_masked
        return services.mask(obj.order.phone_number, obj.order.country.dial_code)

    def get_refund(self, obj) -> dict | None:
        from apps.orders.models import Refund

        refund = Refund.objects.filter(order=services.paying_order(obj)).first()
        if refund is None:
            return None
        return {"reference": refund.reference, "amount": str(refund.amount),
                "reason": refund.reason, "status": refund.status}


class AdminIssueDetailSerializer(AdminIssueSerializer):
    """Adds the number's history, so staff can weigh the report against it."""

    history = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()

    evidence = serializers.SerializerMethodField()
    ticket_pack = serializers.SerializerMethodField()

    class Meta(AdminIssueSerializer.Meta):
        fields = AdminIssueSerializer.Meta.fields + [
            "history", "timeline", "customer", "evidence", "ticket_pack"]
        read_only_fields = fields

    def get_evidence(self, obj) -> list[dict]:
        # The images themselves come from the staff-only evidence endpoint.
        return [
            {"id": str(item.pk), "content_type": item.content_type, "size": item.size,
             "url": f"/admin/number-issues/{obj.reference}/evidence/{item.pk}/",
             "created_at": item.created_at}
            for item in obj.evidence.defer("data")
        ]

    def get_ticket_pack(self, obj) -> dict | None:
        if obj.status != IssueStatus.AWAITING_PROVIDER:
            return None
        return services.ticket_pack(obj)

    def get_history(self, obj) -> dict | None:
        record = obj.number_record
        if record is None:
            return None
        # The same number with this provider, for every service we have sold it
        # for: a report for one service says nothing about the others.
        by_service = [
            {"service": row.service.name, "quality": row.quality,
             "quality_label": row.get_quality_display(), "times_issued": row.times_issued,
             "reports": row.reports_count}
            for row in NumberRecord.objects.filter(
                provider=record.provider, fingerprint=record.fingerprint
            ).select_related("service")
        ]
        usages = [
            {"order": usage.order.reference, "disposition": usage.disposition,
             "acquired_at": usage.acquired_at, "assigned_at": usage.assigned_at,
             "sms_received_at": usage.order.code_received_at,
             "same_customer": usage.user_id == obj.user_id}
            for usage in record.usages.select_related("order")[:20]
        ]
        other_reports = VerificationIssue.objects.filter(number_record=record).exclude(pk=obj.pk)
        return {
            "quality": record.quality,
            "quality_label": record.get_quality_display(),
            "times_issued": record.times_issued,
            "reports": record.reports_count,
            "other_reports_by_other_customers":
                other_reports.exclude(user=obj.user).count(),
            "first_issued_at": record.first_issued_at,
            "by_service": by_service,
            "usages": usages,
            "provider_history_available": False,
        }

    def get_timeline(self, obj) -> dict:
        order = obj.order
        usage = order.number_usages.filter(disposition="ASSIGNED").first()
        return {
            "acquired_at": usage.acquired_at if usage else order.created_at,
            "assigned_at": usage.assigned_at if usage else None,
            "sms_received_at": order.code_received_at,
            "completed_at": order.completed_at,
            "reported_at": obj.created_at,
            "refund_status": services.paying_order(obj).refund_status,
        }

    def get_customer(self, obj) -> dict:
        from apps.orders.models import Order

        user = obj.user
        return {
            "joined": user.created_at,
            "orders": Order.objects.filter(user=user).count(),
            "orders_with_code": Order.objects.filter(
                user=user, code_received_at__isnull=False
            ).count(),
            "reports": VerificationIssue.objects.filter(user=user).count(),
            "remedies": VerificationIssue.objects.filter(
                user=user, status__in=[IssueStatus.REFUNDED, IssueStatus.REPLACED]
            ).count(),
        }


class AdminIssueActionSerializer(serializers.Serializer):
    #: Long enough for a provider's whole reply pasted in (Provider declined).
    reason = serializers.CharField(min_length=5, max_length=2000)
