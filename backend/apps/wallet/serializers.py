from __future__ import annotations

from rest_framework import serializers

from apps.wallet.models import LedgerDirection, Wallet, WalletLedgerEntry


class WalletSerializer(serializers.ModelSerializer):
    #: What the user can actually spend: promotional credit plus cash.
    spendable = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Wallet
        fields = [
            "id",
            "currency",
            "balance",
            "promo_balance",
            "spendable",
            "is_frozen",
            "total_deposited",
            "total_spent",
            "promo_granted",
            "updated_at",
        ]
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    signed_amount = serializers.SerializerMethodField()

    class Meta:
        model = WalletLedgerEntry
        fields = [
            "id",
            "reference",
            "entry_type",
            "funds",
            "direction",
            "status",
            "amount",
            "signed_amount",
            "currency",
            "balance_after",
            "description",
            "related_order_id",
            "related_payment_id",
            "created_at",
        ]
        read_only_fields = fields

    def get_signed_amount(self, obj: WalletLedgerEntry) -> str:
        return str(obj.amount if obj.direction == LedgerDirection.CREDIT else -obj.amount)
