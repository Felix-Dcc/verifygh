"""Referral API for signed-in users.

There is deliberately **no claim endpoint**. The reward is decided by the
backend when the account becomes eligible - email verification, an admin
review, or the periodic sweep. A "claim" button would be a request from the
browser to be given money, and no amount of validation makes that a good
shape for a payments system.
"""

from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.permissions import IsActiveUser
from apps.common.throttling import ResilientThrottleMixin
from apps.referrals.models import Referral, ReferralProgram
from apps.referrals.serializers import ReferralHistorySerializer, ValidateCodeSerializer
from apps.referrals.services import code_for, resolve_code, stats_for


class ReferralValidateThrottle(ResilientThrottleMixin, AnonRateThrottle):
    """Stops the validate endpoint becoming a code-guessing oracle."""

    scope = "referral_validate"


class ReferralStatusView(APIView):
    """Whether the programme is running - so the app can hide it while paused."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"enabled": ReferralProgram.load().is_enabled})


def _terms(program: ReferralProgram) -> dict:
    """What each side gets and what unlocks it - shown wherever the offer is."""
    return {
        "bonus_amount": str(program.signup_bonus),
        "referrer_bonus": str(program.referrer_bonus),
        "require_first_deposit": program.require_first_deposit,
        "min_first_deposit": str(program.min_first_deposit),
        "currency": program.currency,
    }


class MyReferralView(APIView):
    """The user's own code, link and the current terms."""

    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        program = ReferralProgram.load()
        code = code_for(request.user)
        return Response(
            {
                "enabled": program.is_enabled,
                "code": code.code,
                "share_url": code.share_url,
                **_terms(program),
                "stats": stats_for(request.user),
            }
        )


class ReferralStatsView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        return Response(stats_for(request.user))


class ReferralHistoryView(APIView):
    """Only ever the caller's own referrals - the queryset is filtered by owner."""

    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        referrals = (
            Referral.objects.filter(referrer=request.user)
            .select_related("referred_user", "reward", "referrer_reward")
            .order_by("-created_at")[:100]
        )
        return Response({"results": ReferralHistorySerializer(referrals, many=True).data})


class ValidateReferralCodeView(APIView):
    """Used by the registration page to show the invitation banner.

    Answers only whether the code can be used and what the bonus is. It never
    says who owns it, and an invalid code is not an error: registration
    continues without a referral.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ReferralValidateThrottle]

    def post(self, request):
        serializer = ValidateCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        program = ReferralProgram.load()
        entry = resolve_code(serializer.validated_data["code"]) if program.is_enabled else None
        return Response(
            {
                "valid": entry is not None,
                "enabled": program.is_enabled,
                **_terms(program),
            }
        )
