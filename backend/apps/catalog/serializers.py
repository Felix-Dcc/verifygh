from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import Country, Service


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["code", "name", "dial_code", "flag_emoji"]
        read_only_fields = fields


class ServiceCountryOptionSerializer(serializers.Serializer):
    """One purchasable (service, country) combination, priced by the server.

    Everything here - price, availability, capabilities - is derived on the
    backend from the catalog and the pricing engine. The frontend renders it
    and nothing more; it has no pricing logic of its own.
    """

    code = serializers.CharField()
    name = serializers.CharField()
    flag_emoji = serializers.CharField()
    dial_code = serializers.CharField()
    price = serializers.CharField()
    currency = serializers.CharField()
    available = serializers.BooleanField()
    available_count = serializers.IntegerField(allow_null=True)
    supports_sms = serializers.BooleanField()
    supports_voice = serializers.BooleanField()
    ttl_minutes = serializers.IntegerField()


class ServiceSerializer(serializers.ModelSerializer):
    countries = ServiceCountryOptionSerializer(many=True, read_only=True)
    from_price = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True, default="GHS")
    available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Service
        fields = [
            "slug",
            "name",
            "category",
            "icon_url",
            "accent_color",
            "description",
            "supports_sms",
            "supports_voice",
            "is_maintenance",
            "maintenance_note",
            "available",
            "from_price",
            "currency",
            "countries",
        ]
        read_only_fields = fields
