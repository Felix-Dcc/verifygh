from __future__ import annotations

from rest_framework import serializers

from apps.orders.models import Order, OrderEvent, OrderStatus, Refund


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ["id", "status", "label", "detail", "created_at"]
        read_only_fields = fields


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ["reference", "amount", "currency", "reason", "status", "completed_at"]
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    service_slug = serializers.CharField(source="service.slug", read_only=True)
    service_icon = serializers.CharField(source="service.icon_url", read_only=True)
    country_name = serializers.CharField(source="country.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    country_flag = serializers.CharField(source="country.flag_emoji", read_only=True)
    country_dial_code = serializers.CharField(source="country.dial_code", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "reference",
            "service_name",
            "service_slug",
            "service_icon",
            "country_name",
            "country_code",
            "country_flag",
            "country_dial_code",
            "phone_number",
            "price",
            "currency",
            "status",
            "refund_status",
            "expires_at",
            "created_at",
        ]
        read_only_fields = fields


class OrderDetailSerializer(OrderListSerializer):
    """Full order view, including the timeline.

    The verification code is exposed **only** to the ordering user, and only
    when the provider agreement permits relaying it. Everywhere else it is an
    empty string - including in admin list views and in every log line.
    """

    events = OrderEventSerializer(many=True, read_only=True)
    refund = RefundSerializer(read_only=True)
    verification_code = serializers.SerializerMethodField()
    verification_message = serializers.SerializerMethodField()
    code_display_allowed = serializers.SerializerMethodField()
    seconds_remaining = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_complete = serializers.SerializerMethodField()
    can_report = serializers.SerializerMethodField()
    report_window_ends_at = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()
    replacement_for = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            "provider_cost",
            "provider_currency",
            "exchange_rate",
            "failure_reason",
            "verification_code",
            "verification_message",
            "code_display_allowed",
            "code_received_at",
            "completed_at",
            "seconds_remaining",
            "can_cancel",
            "can_complete",
            "events",
            "refund",
            "can_report",
            "report_window_ends_at",
            "issue",
            "replacement_for",
        ]
        read_only_fields = fields

    def get_can_report(self, obj: Order) -> bool:
        from apps.numbers.services import can_report

        return self._is_owner(obj) and can_report(obj)

    def get_report_window_ends_at(self, obj: Order):
        from apps.numbers.services import report_window_ends

        return report_window_ends(obj)

    def get_issue(self, obj: Order) -> dict | None:
        from apps.numbers.serializers import CustomerIssueSerializer
        from apps.numbers.services import issue_for

        issue = issue_for(obj)
        return CustomerIssueSerializer(issue).data if issue else None

    def get_replacement_for(self, obj: Order) -> str | None:
        return (obj.metadata or {}).get("replacement_for")

    def _is_owner(self, obj: Order) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.user_id == request.user.id)

    def get_code_display_allowed(self, obj: Order) -> bool:
        return obj.may_display_code

    def get_verification_code(self, obj: Order) -> str:
        if not self._is_owner(obj) or not obj.may_display_code:
            return ""
        return obj.verification_code

    def get_verification_message(self, obj: Order) -> str:
        if not self._is_owner(obj) or not obj.may_display_code:
            return ""
        return obj.verification_message

    def get_seconds_remaining(self, obj: Order) -> int:
        from django.utils import timezone

        if not obj.expires_at or obj.is_terminal:
            return 0
        return max(0, int((obj.expires_at - timezone.now()).total_seconds()))

    def get_can_cancel(self, obj: Order) -> bool:
        return obj.status in {
            OrderStatus.PROCESSING,
            OrderStatus.NUMBER_ASSIGNED,
            OrderStatus.WAITING_FOR_CODE,
        }

    def get_can_complete(self, obj: Order) -> bool:
        return obj.status == OrderStatus.CODE_RECEIVED


class CreateOrderSerializer(serializers.Serializer):
    """Note what is *not* here: price.

    The client tells us what it wants, never what it costs. The server prices
    the order from the catalog every single time.
    """

    service = serializers.SlugField(max_length=64)
    country = serializers.CharField(max_length=2)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)

    def validate_country(self, value: str) -> str:
        return value.upper()


class QuoteSerializer(serializers.Serializer):
    service = serializers.SlugField(max_length=64)
    country = serializers.CharField(max_length=2)

    def validate_country(self, value: str) -> str:
        return value.upper()
