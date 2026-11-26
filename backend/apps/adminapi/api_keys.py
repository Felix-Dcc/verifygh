"""Admin > API keys: each staff member's own keys for programs and assistants.

Keys are personal: you see, make and revoke your own, and a key acts as you.
Making one needs a fresh two-factor code, because the key outlives the session
that made it. A request made *with* a key can never reach these endpoints (the
authentication layer refuses it first; the check here is the second lock).
"""

from __future__ import annotations

from django.db import transaction
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts import api_keys, two_factor
from apps.accounts.models import AdminApiKey, ApiKeyAccess
from apps.adminapi.views import AdminBase
from apps.audit.services import record_admin_action
from apps.common.errors import ValidationFailed


class AdminApiKeySerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    display = serializers.SerializerMethodField()

    class Meta:
        model = AdminApiKey
        fields = ["id", "name", "prefix", "display", "access", "status", "expires_at",
                  "last_used_at", "last_used_ip", "revoked_at", "created_at"]
        read_only_fields = fields

    def get_display(self, obj) -> str:
        return f"{api_keys.KEY_MARKER}{obj.prefix}_…"


class CreateApiKeySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, min_length=2)
    access = serializers.ChoiceField(choices=ApiKeyAccess.choices, default=ApiKeyAccess.READ)
    days = serializers.ChoiceField(choices=api_keys.ALLOWED_DAYS, default=30)
    code = serializers.CharField(max_length=32, required=False, allow_blank=True)


class AdminApiKeyViewSet(AdminBase, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AdminApiKeySerializer
    required_permission = None  # any staff member, for their own keys
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request.auth, "is_admin_api_key", False):
            raise PermissionDenied("API keys cannot manage API keys.")

    def get_queryset(self):
        return (AdminApiKey.objects.select_related("owner")
                .filter(owner=self.request.user).order_by("-created_at"))

    def list(self, request):
        return Response(AdminApiKeySerializer(self.get_queryset()[:50], many=True).data)

    def create(self, request):
        data = CreateApiKeySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if not user.is_two_factor_enabled:
            raise ValidationFailed(
                "Turn on two-factor sign-in before creating an API key.",
                code="TWO_FACTOR_REQUIRED")
        if not two_factor.verify_code_or_recovery(user, data.validated_data.get("code", "")):
            raise ValidationFailed("That two-factor code is not right. Try a fresh one.",
                                   code="INVALID_TWO_FACTOR_CODE")

        with transaction.atomic():
            key, raw = api_keys.create_key(
                owner=user, name=data.validated_data["name"],
                access=data.validated_data["access"], days=int(data.validated_data["days"]),
            )
            record_admin_action(
                admin=user, action="API_KEY_CREATE", target=key,
                reason=f"Created API key '{key.name}'",
                after={"prefix": key.prefix, "key_access": key.access,
                       "expires_at": key.expires_at.isoformat()},
                request=request,
            )
        body = AdminApiKeySerializer(key).data
        # The only time the full key is ever sent.
        body["key"] = raw
        return Response(body, status=201)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        key = self.get_object()
        with transaction.atomic():
            was_live = key.revoked_at is None
            api_keys.revoke_key(key, by=request.user)
            if was_live:
                record_admin_action(
                    admin=request.user, action="API_KEY_REVOKE", target=key,
                    reason=f"Revoked API key '{key.name}'", request=request,
                )
        return Response(AdminApiKeySerializer(key).data)
