"""Customer-facing referral serialisers.

Two rules shape everything here:

* a referrer learns nothing about the people they invited beyond a masked
  email and a status, so a referral link is not a way to harvest contacts;
* fraud signals never leave the building. A flagged referral reads as
  "pending" to the customer - telling someone which check caught them is a
  tutorial in evading it.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.referrals.models import Referral, ReferralStatus

#: What the customer sees for each internal status.
PUBLIC_STATUS = {
    ReferralStatus.PENDING: "PENDING",
    ReferralStatus.ELIGIBLE: "PENDING",
    ReferralStatus.FRAUD_FLAGGED: "PENDING",
    ReferralStatus.REWARDED: "REWARDED",
    ReferralStatus.REJECTED: "REJECTED",
}


def mask_email(email: str) -> str:
    """kwame@example.com -> k***@example.com"""
    if not email or "@" not in email:
        return "a member"
    name, _, domain = email.partition("@")
    return f"{name[0]}***@{domain}"


class ReferralHistorySerializer(serializers.ModelSerializer):
    friend = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    reward_amount = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = ["friend", "status", "reward_amount", "created_at", "rewarded_at"]
        read_only_fields = fields

    def get_friend(self, obj: Referral) -> str:
        return mask_email(obj.referred_user.email)

    def get_status(self, obj: Referral) -> str:
        return PUBLIC_STATUS.get(obj.status, "PENDING")

    def get_reward_amount(self, obj: Referral) -> str | None:
        reward = getattr(obj, "reward", None)
        return str(reward.amount) if reward is not None else None


class ValidateCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16, allow_blank=True)
