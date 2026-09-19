from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from apps.accounts.constants import MomoNetwork
from apps.accounts.phone import InvalidPhoneNumber, detect_network, format_local, normalise_gh
from apps.payments.models import Payment


class DepositSerializer(serializers.Serializer):
    """Start a MoMo deposit.

    The network is optional: we can infer it from the number's prefix, which is
    one less thing for the user to get wrong on a phone keyboard.
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
        elif detected and detected != network:
            # Trust the prefix over the dropdown: sending a charge to the wrong
            # network just fails at the aggregator.
            attrs["network"] = detected

        minimum = Decimal(str(settings.VERIFYGH["MIN_DEPOSIT"]))
        maximum = Decimal(str(settings.VERIFYGH["MAX_DEPOSIT"]))
        if attrs["amount"] < minimum:
            raise serializers.ValidationError(
                {"amount": f"The minimum deposit is GHS {minimum}."}
            )
        if attrs["amount"] > maximum:
            raise serializers.ValidationError(
                {"amount": f"The maximum single deposit is GHS {maximum}."}
            )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    phone_display = serializers.SerializerMethodField()
    network_label = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "reference",
            "amount",
            "currency",
            "status",
            "network",
            "network_label",
            "phone_display",
            "instructions",
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


class MomoNetworkSerializer(serializers.Serializer):
    """Payment options are served from the backend, never hardcoded in the UI,
    so enabling a network is a deploy-free change."""

    value = serializers.CharField()
    label = serializers.CharField()
    prefixes = serializers.ListField(child=serializers.CharField())
