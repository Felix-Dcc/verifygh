from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.phone import InvalidPhoneNumber, format_local, normalise_gh


class PhoneField(serializers.CharField):
    """Accepts any Ghanaian format, stores E.164."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalise_gh(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(str(exc)) from exc


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=10, max_length=128)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = PhoneField(required=False, allow_blank=True, default="")
    accepted_terms = serializers.BooleanField()
    #: Optional, from /register?ref=CODE. Never trusted: the backend resolves
    #: it, and silently ignores anything it does not recognise.
    referral_code = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            # Registration is throttled to 5/hour per IP, which keeps this from
            # being a practical enumeration channel while keeping the error useful.
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_phone(self, value: str) -> str:
        if value and User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("This mobile number is already in use.")
        return value

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_accepted_terms(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "You must accept the Terms and Acceptable Use Policy."
            )
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class UserSerializer(serializers.ModelSerializer):
    phone_display = serializers.SerializerMethodField()
    has_accepted_current_terms = serializers.BooleanField(read_only=True)
    admin_permissions = serializers.ListField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "phone_display",
            "role",
            "is_email_verified",
            "is_phone_verified",
            "is_suspended",
            "is_two_factor_enabled",
            "has_accepted_current_terms",
            "accepted_terms_version",
            "admin_permissions",
            "created_at",
        ]
        read_only_fields = fields

    def get_phone_display(self, obj: User) -> str:
        return format_local(obj.phone) if obj.phone else ""


class UpdateProfileSerializer(serializers.ModelSerializer):
    phone = PhoneField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["full_name", "phone"]

    def validate_phone(self, value: str) -> str:
        if value and User.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This mobile number is already in use.")
        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=10, max_length=128)

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Your current password is incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        validate_password(value, self.context["request"].user)
        return value


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)
    new_password = serializers.CharField(write_only=True, min_length=10, max_length=128)


class AcceptTermsSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()

    def validate_accepted(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError("You must accept to continue.")
        return value
