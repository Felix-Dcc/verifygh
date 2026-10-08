from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from apps.accounts.constants import MomoNetwork
from apps.accounts.phone import InvalidPhoneNumber, detect_network, format_local, normalise_gh
from apps.common.money import format_ghs
from apps.payments.models import Payment, PaymentStatus


class ManualDepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class DepositSerializer(serializers.Serializer):
    """Start a MoMo deposit.

    The network is optional: when it is missing we infer it from the number's
    prefix. When the customer states one, theirs wins.

    That order matters, and it used to be the other way round. Ghana has had
    mobile number portability since 2011: a number keeps its original prefix
    when its owner moves network. A customer on Telecel with an 026 number -
    originally AirtelTigo - was having their explicit choice silently replaced
    by the prefix, so the charge went to AirtelTigo Money, where they have no
    wallet, and the one-time code they were waiting for never came.

    The prefix knows which network issued a number. Only the customer knows
    which network it is on today.
    """

    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    phone = serializers.CharField(max_length=20)
    network = serializers.ChoiceField(choices=MomoNetwork.choices, required=False)

    def validate_phone(self, value: str) -> str:
        try:
            return normalise_gh(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        phone = attrs["phone"]
        network = attrs.get("network")
        detected = detect_network(phone)

        if not network:
            if not detected:
                raise serializers.ValidationError(
                    {"network": "We could not tell which network this number is on. "
                                "Please choose it."}
                )
            attrs["network"] = detected
            attrs["network_source"] = "prefix"
        else:
            # The customer's choice stands, even against the prefix. Recorded
            # when they disagree, because that pair is exactly what support
            # needs to see when someone reports a code that never arrived.
            attrs["network_source"] = "customer"
            attrs["detected_network"] = detected or ""

        minimum = Decimal(str(settings.VERIFYGH["MIN_DEPOSIT"]))
        maximum = Decimal(str(settings.VERIFYGH["MAX_DEPOSIT"]))
        if attrs["amount"] < minimum:
            raise serializers.ValidationError(
                {"amount": f"The minimum deposit is {format_ghs(minimum)}."}
            )
        if attrs["amount"] > maximum:
            raise serializers.ValidationError(
                {"amount": f"The maximum single deposit is {format_ghs(maximum)}."}
            )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    phone_display = serializers.SerializerMethodField()
    network_label = serializers.SerializerMethodField()
    checkout_url = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "reference",
            "provider",
            "amount",
            "currency",
            "status",
            "network",
            "network_label",
            "phone_display",
            "instructions",
            "checkout_url",
            "failure_reason",
            "expires_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_phone_display(self, obj: Payment) -> str:
        return format_local(obj.phone)

    def get_network_label(self, obj: Payment) -> str:
        return MomoNetwork(obj.network).label if obj.network else ""

    def get_checkout_url(self, obj: Payment) -> str:
        """The hosted checkout page, only while the payment is still open."""
        from apps.payments.sendi import safe_checkout_url

        if obj.status != PaymentStatus.PENDING:
            return ""
        return safe_checkout_url((obj.metadata or {}).get("checkout_url", ""))


class MomoNetworkSerializer(serializers.Serializer):
    """Payment options are served from the backend, never hardcoded in the UI,
    so enabling a network is a deploy-free change."""

    value = serializers.CharField()
    label = serializers.CharField()
    prefixes = serializers.ListField(child=serializers.CharField())


class SubmitOtpSerializer(serializers.Serializer):
    """The one-time code a customer read off their phone.

    Deliberately permissive about shape - spaces and dashes get pasted in - and
    strict about length, which the service checks again after stripping. Marked
    write_only so it cannot be echoed back in a response by accident.
    """

    otp = serializers.CharField(max_length=16, trim_whitespace=True, write_only=True)
