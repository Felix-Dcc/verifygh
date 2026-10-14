from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from apps.rentals import services
from apps.rentals.models import Rental, RentalExtension, RentalMessage


class CreateRentalSerializer(serializers.Serializer):
    #: A catalogue service slug, or "all" for a number any app can text.
    service = serializers.CharField(max_length=64)
    days = serializers.IntegerField(min_value=1, max_value=365)
    #: The price the customer was shown. A different live price is refused
    #: (PRICE_CHANGED) rather than charged.
    expected_price = serializers.DecimalField(max_digits=12, decimal_places=2,
                                              required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class ExtendRentalSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=365)
    expected_price = serializers.DecimalField(max_digits=12, decimal_places=2,
                                              required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class RentalMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalMessage
        fields = ["id", "sender", "body", "code", "received_at"]
        read_only_fields = fields


class RentalExtensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalExtension
        fields = ["id", "days", "price", "status", "new_ends_at", "created_at"]
        read_only_fields = fields


class RentalListSerializer(serializers.ModelSerializer):
    service_slug = serializers.SerializerMethodField()
    service_name = serializers.CharField(source="service_label", read_only=True)
    service_icon = serializers.SerializerMethodField()
    all_services = serializers.BooleanField(source="is_all_services", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    duration_label = serializers.SerializerMethodField()
    seconds_remaining = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Rental
        fields = [
            "id", "reference", "service_slug", "service_name", "service_icon", "all_services",
            "days",
            "duration_label", "price", "currency", "status", "status_label", "phone_number",
            "activated_at", "ends_at", "ended_at", "seconds_remaining", "message_count",
            "refunded_amount", "created_at",
        ]
        read_only_fields = fields

    def get_service_slug(self, rental: Rental) -> str:
        return rental.service.slug if rental.service_id else "all"

    def get_service_icon(self, rental: Rental) -> str:
        return rental.service.icon_url if rental.service_id else ""

    def get_duration_label(self, rental: Rental) -> str:
        return services.duration_label(rental.days)

    def get_seconds_remaining(self, rental: Rental) -> int:
        if rental.status != "ACTIVE" or not rental.ends_at:
            return 0
        return max(0, int((rental.ends_at - timezone.now()).total_seconds()))

    def get_message_count(self, rental: Rental) -> int:
        annotated = getattr(rental, "message_total", None)
        return annotated if annotated is not None else rental.messages.count()


class RentalDetailSerializer(RentalListSerializer):
    """One rental with its inbox. Message text only where codes may be shown."""

    messages = serializers.SerializerMethodField()
    messages_hidden = serializers.SerializerMethodField()
    extensions = RentalExtensionSerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()
    cancel_note = serializers.SerializerMethodField()
    poll_interval_seconds = serializers.SerializerMethodField()

    class Meta(RentalListSerializer.Meta):
        fields = RentalListSerializer.Meta.fields + [
            "failure_reason", "refundable_until", "can_cancel", "cancel_note", "messages",
            "messages_hidden", "extensions", "promo_amount", "cash_amount",
            "poll_interval_seconds",
        ]
        read_only_fields = fields

    def get_messages(self, rental: Rental) -> list:
        if not rental.may_display_messages:
            return []
        return RentalMessageSerializer(rental.messages.all()[:200], many=True).data

    def get_messages_hidden(self, rental: Rental) -> bool:
        return not rental.may_display_messages

    def get_can_cancel(self, rental: Rental) -> bool:
        return not services.cancel_blocker(rental)

    def get_cancel_note(self, rental: Rental) -> str:
        return services.cancel_blocker(rental) if rental.status == "ACTIVE" else ""

    def get_poll_interval_seconds(self, rental: Rental) -> int:
        return services.LIVE_SYNC_SECONDS if rental.status in ("ACTIVE", "PENDING") else 0


class AdminRentalSerializer(RentalListSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta(RentalListSerializer.Meta):
        fields = RentalListSerializer.Meta.fields + [
            "user_email", "provider_name", "provider_service_name", "provider_cost",
            "provider_currency", "exchange_rate", "provider_rental_id", "provider_sale_id",
            "failure_reason", "promo_amount", "cash_amount", "attempts",
        ]
        read_only_fields = fields
