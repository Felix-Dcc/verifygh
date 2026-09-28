from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.models import User
from apps.audit.models import AdminAction, AuditLog, SuspiciousActivity
from apps.catalog.models import Country, ProviderService, Service
from apps.orders.models import Order, Refund
from apps.payments.models import Payment
from apps.pricing.models import ExchangeRate, PricingRule


class AdminUserSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    promo_balance = serializers.SerializerMethodField()
    order_count = serializers.IntegerField(read_only=True, default=0)
    open_flags = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "phone", "role", "is_active", "is_suspended",
            "suspension_reason", "is_email_verified", "is_phone_verified", "risk_score",
            "balance", "promo_balance", "order_count", "open_flags", "last_login",
            "created_at",
        ]
        read_only_fields = fields

    def get_balance(self, obj: User) -> str:
        wallet = getattr(obj, "wallet", None)
        return str(wallet.balance) if wallet else "0.00"

    def get_promo_balance(self, obj: User) -> str:
        """Promotional credit, shown apart from cash so staff never confuse the two."""
        wallet = getattr(obj, "wallet", None)
        return str(wallet.promo_balance) if wallet else "0.00"


class SuspendUserSerializer(serializers.Serializer):
    """Suspension always carries a reason - it is shown to the user and audited."""

    reason = serializers.CharField(max_length=500, min_length=5)


class WalletAdjustmentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    direction = serializers.ChoiceField(choices=["CREDIT", "DEBIT"])
    reason = serializers.CharField(max_length=500, min_length=5)


class AdminOrderSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    has_code = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "reference", "user_id", "user_email", "service_name", "country_code",
            "provider_name", "provider_order_id", "phone_number", "price", "currency",
            "provider_cost", "provider_currency", "exchange_rate", "status", "refund_status",
            "failure_reason", "has_code", "expires_at", "completed_at", "created_at",
        ]
        read_only_fields = fields

    def get_has_code(self, obj: Order) -> bool:
        """Whether a code arrived - never the code itself.

        Admins can see that verification succeeded without being able to read
        the one-time code from a list view.
        """
        return bool(obj.verification_code)


class AdminRefundSerializer(serializers.ModelSerializer):
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    issued_by_email = serializers.CharField(source="issued_by.email", read_only=True)

    class Meta:
        model = Refund
        fields = [
            "id", "reference", "order_reference", "amount", "currency", "reason", "note",
            "status", "is_automatic", "issued_by_email", "provider_refund_requested",
            "provider_refund_accepted", "completed_at", "created_at",
        ]
        read_only_fields = fields


class IssueRefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=500, min_length=5)


class AdminPaymentSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "reference", "user_email", "provider", "provider_reference", "amount",
            "currency", "network", "status", "failure_reason", "credited_at",
            "completed_at", "created_at",
        ]
        read_only_fields = fields


class AdminPaymentDetailSerializer(AdminPaymentSerializer):
    """Everything support needs to answer "why did this deposit fail?".

    Built after a Telecel report took a database session to diagnose: the
    customer's number was ported, their network choice had been overridden, and
    Paystack had asked for a code that never arrived. Every one of those facts
    is on this view now.

    Deliberately absent: the full phone number, the one-time code (it is never
    stored), and any credential. `phone_suffix` is enough to confirm a caller is
    who they say they are.
    """

    network_label = serializers.CharField(source="get_network_display", read_only=True)
    phone_suffix = serializers.SerializerMethodField()
    network_source = serializers.SerializerMethodField()
    prefix_network = serializers.SerializerMethodField()
    provider_status_initial = serializers.SerializerMethodField()
    provider_status_latest = serializers.SerializerMethodField()
    provider_checked_at = serializers.SerializerMethodField()
    webhook_events = serializers.SerializerMethodField()

    class Meta(AdminPaymentSerializer.Meta):
        fields = AdminPaymentSerializer.Meta.fields + [
            "network_label", "phone_suffix", "instructions", "otp_attempts", "expires_at",
            "network_source", "prefix_network",
            "provider_status_initial", "provider_status_latest", "provider_checked_at",
            "webhook_events",
        ]
        read_only_fields = fields

    def get_phone_suffix(self, obj) -> str:
        return f"***{obj.phone[-4:]}" if obj.phone else ""

    def _meta(self, obj, key):
        return (obj.metadata or {}).get(key, "")

    def get_network_source(self, obj) -> str:
        return self._meta(obj, "network_source")

    def get_prefix_network(self, obj) -> str:
        return self._meta(obj, "prefix_network")

    def get_provider_status_initial(self, obj) -> str:
        return self._meta(obj, "provider_status_initial")

    def get_provider_status_latest(self, obj) -> str:
        return self._meta(obj, "provider_status_latest")

    def get_provider_checked_at(self, obj) -> str:
        return self._meta(obj, "provider_checked_at")

    def get_webhook_events(self, obj) -> list[dict]:
        # Payload and headers stay out: they are raw provider data, and the
        # signature header is not something to put on a support screen.
        return [
            {
                "event_type": event.event_type,
                "signature_valid": event.signature_valid,
                "processed": event.processed,
                "processing_error": (event.processing_error or "")[:200],
                "received_at": event.created_at,
            }
            for event in obj.webhook_events.order_by("created_at")
        ]


class AdminServiceSerializer(serializers.ModelSerializer):
    offering_count = serializers.IntegerField(read_only=True, default=0)
    available_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Service
        fields = [
            "id", "slug", "name", "category", "description", "accent_color", "icon_url",
            "aliases", "is_popular", "popular_rank",
            "is_enabled", "is_maintenance", "maintenance_note", "supports_sms",
            "supports_voice", "display_order", "offering_count", "available_count",
        ]
        read_only_fields = ["id", "slug", "offering_count", "available_count"]


class AdminCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "code", "name", "dial_code", "flag_emoji", "is_enabled",
                  "display_order"]
        read_only_fields = ["id", "code"]


class AdminOfferingSerializer(serializers.ModelSerializer):
    """Provider cost next to customer price, so margin is visible at a glance."""

    service_name = serializers.CharField(source="service.name", read_only=True)
    service_slug = serializers.CharField(source="service.slug", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    customer_price = serializers.SerializerMethodField()
    margin = serializers.SerializerMethodField()
    base_cost = serializers.SerializerMethodField()
    cost_floor = serializers.SerializerMethodField()
    pricing_rule_name = serializers.SerializerMethodField()
    pricing_error = serializers.SerializerMethodField()

    class Meta:
        model = ProviderService
        fields = [
            "id", "provider_name", "service_name", "service_slug", "country_code",
            "provider_service_code", "cost_amount", "cost_currency", "base_cost", "cost_floor",
            "customer_price", "margin", "pricing_rule_name", "pricing_error", "is_enabled",
            "is_available", "available_count", "supports_sms", "supports_voice",
            "ttl_minutes", "last_synced_at", "price_updated_at",
        ]
        # Only is_enabled is an admin decision. Everything else describes what
        # the provider sells and comes from catalog sync; letting an admin
        # rewrite provider_service_code would change what is bought upstream
        # while the customer still sees the old service.
        read_only_fields = [
            "id", "provider_name", "service_name", "service_slug", "country_code",
            "provider_service_code", "cost_amount", "cost_currency", "customer_price",
            "margin", "pricing_error", "is_available", "available_count", "supports_sms",
            "supports_voice", "ttl_minutes", "last_synced_at",
        ]

    def _quote(self, obj: ProviderService):
        cached = getattr(obj, "_admin_quote", None)
        if cached is not None:
            return cached
        from apps.pricing.engine import NoPricingRule, quote_for_offering

        try:
            quote = quote_for_offering(obj)
        except (NoPricingRule, Exception):  # noqa: B014 - surfaced, not swallowed
            quote = None
        obj._admin_quote = quote
        return quote

    def get_customer_price(self, obj) -> str | None:
        quote = self._quote(obj)
        return str(quote.customer_price) if quote else None

    def get_margin(self, obj) -> str | None:
        quote = self._quote(obj)
        return str(quote.margin) if quote else None

    def get_base_cost(self, obj) -> str | None:
        """Provider cost converted to cedis at the current rate."""
        quote = self._quote(obj)
        return str(quote.base_cost) if quote else None

    def get_cost_floor(self, obj) -> str | None:
        quote = self._quote(obj)
        return quote.applied.get("cost_floor") if quote else None

    def get_pricing_rule_name(self, obj) -> str:
        quote = self._quote(obj)
        return quote.pricing_rule_name if quote else ""

    def get_pricing_error(self, obj) -> str:
        return "" if self._quote(obj) else "Could not price this offering."


class PricingRuleSerializer(serializers.ModelSerializer):
    service_slug = serializers.CharField(source="service.slug", read_only=True, default=None)
    service_name = serializers.CharField(source="service.name", read_only=True, default=None)
    country_code = serializers.CharField(source="country.code", read_only=True, default=None)
    provider_key = serializers.CharField(source="provider.adapter_key", read_only=True,
                                         default=None)

    class Meta:
        model = PricingRule
        fields = [
            "id", "name", "is_active", "service", "service_slug", "service_name", "country",
            "country_code", "provider", "provider_key", "markup_type", "markup_percent",
            "markup_fixed", "payment_fee_percent", "risk_buffer_percent", "rounding",
            "min_price", "max_price", "allow_below_cost", "priority", "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "service_slug", "service_name", "country_code",
                            "provider_key", "created_at", "updated_at"]

    def validate(self, attrs):
        minimum = attrs.get("min_price", getattr(self.instance, "min_price", None))
        maximum = attrs.get("max_price", getattr(self.instance, "max_price", None))
        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError(
                {"min_price": "The minimum price cannot exceed the maximum price."}
            )
        return attrs


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ["id", "base_currency", "quote_currency", "rate", "source", "note",
                  "is_active", "fetched_at"]
        read_only_fields = ["id", "fetched_at", "source"]


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "actor_email", "action", "target_type", "target_id", "ip_address",
                  "request_id", "metadata", "created_at"]
        read_only_fields = fields


class AdminActionSerializer(serializers.ModelSerializer):
    admin_email = serializers.CharField(source="admin.email", read_only=True)

    class Meta:
        model = AdminAction
        fields = ["id", "admin_email", "action", "target_type", "target_id", "reason",
                  "before", "after", "created_at"]
        read_only_fields = fields


class SuspiciousActivitySerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True, default="")

    class Meta:
        model = SuspiciousActivity
        fields = ["id", "user", "user_email", "kind", "level", "description", "evidence",
                  "resolved", "resolved_at", "resolution_note", "created_at"]
        read_only_fields = [field for field in fields if field != "resolution_note"]


class ResolveFlagSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, min_length=3)


class PriceChangeSerializer(serializers.ModelSerializer):
    changed_by_email = serializers.EmailField(source="changed_by.email", default=None,
                                              read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        from apps.pricing.models import PriceChange

        model = PriceChange
        fields = ["id", "service_name", "country_code", "provider_key", "old_price",
                  "new_price", "currency", "provider_cost", "provider_currency",
                  "exchange_rate", "pricing_rule_name", "source", "source_label",
                  "changed_by_email", "reason", "created_at"]
        read_only_fields = fields
