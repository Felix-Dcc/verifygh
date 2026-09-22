"""Referral programme: codes, attributions, rewards and risk flags.

Four tables, no duplication of the user or the wallet:

* `ReferralCode`   - one per user, the thing they share.
* `Referral`       - one per *referred* user, created at registration. Its
                     uniqueness is what stops a second referrer being attached
                     later.
* `ReferralReward` - one per referral, pointing at the ledger entry that
                     actually granted the credit. Its uniqueness is what stops
                     a second reward.
* `ReferralRiskFlag` - why a referral was held or rejected, kept out of the
                     customer-facing API.

The money itself lives where all money lives: the wallet ledger.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.common.models import BaseModel


class ReferralStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ELIGIBLE = "ELIGIBLE", "Eligible"
    REWARDED = "REWARDED", "Rewarded"
    REJECTED = "REJECTED", "Rejected"
    FRAUD_FLAGGED = "FRAUD_FLAGGED", "Flagged for fraud review"


#: Statuses a referral can never leave on its own. An admin can still act.
TERMINAL_REFERRAL_STATUSES = frozenset({ReferralStatus.REWARDED, ReferralStatus.REJECTED})


class RiskLevel(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class RiskKind(models.TextChoices):
    SELF_REFERRAL = "SELF_REFERRAL", "Referrer and referred user are the same"
    SHARED_EMAIL = "SHARED_EMAIL", "Same email address as the referrer"
    SHARED_PHONE = "SHARED_PHONE", "Same phone number as the referrer"
    SHARED_DEVICE = "SHARED_DEVICE", "Same device as the referrer"
    SHARED_IP = "SHARED_IP", "Same IP address as the referrer"
    DUPLICATE_ACCOUNT = "DUPLICATE_ACCOUNT", "Looks like an existing user's second account"
    REFERRER_VELOCITY = "REFERRER_VELOCITY", "Unusually fast referral sign-ups"
    MONTHLY_LIMIT = "MONTHLY_LIMIT", "Referrer is at the monthly limit"
    REFERRER_SUSPENDED = "REFERRER_SUSPENDED", "Referrer is suspended"
    ALREADY_BONUSED = "ALREADY_BONUSED", "User already received a signup bonus"


class ReferralProgram(BaseModel):
    """Programme configuration, editable by a super admin.

    Environment variables seed the first row; after that the database is the
    source of truth, so changing the bonus does not need a deploy. There is
    exactly one row.
    """

    SINGLETON_NAME = "default"

    name = models.CharField(max_length=32, unique=True, default=SINGLETON_NAME)
    is_enabled = models.BooleanField(default=True)
    signup_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("5.00"))
    currency = models.CharField(max_length=3, default="GHS")
    max_monthly_successful_referrals = models.PositiveIntegerField(default=20)
    #: Sign-ups from one referrer within an hour before the velocity flag.
    velocity_per_hour = models.PositiveIntegerField(default=5)
    require_email_verification = models.BooleanField(default=True)
    require_phone_verification = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referral_program_updates",
    )

    class Meta:
        db_table = "referrals_program"
        constraints = [
            models.CheckConstraint(
                check=Q(signup_bonus__gte=Decimal("0.00")), name="referral_bonus_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"ReferralProgram<{self.currency} {self.signup_bonus}>"

    @classmethod
    def load(cls) -> ReferralProgram:
        """The one row, created from settings the first time it is needed."""
        config = settings.VERIFYGH
        program, _ = cls.objects.get_or_create(
            name=cls.SINGLETON_NAME,
            defaults={
                "is_enabled": config["REFERRAL_PROGRAM_ENABLED"],
                "signup_bonus": Decimal(str(config["REFERRAL_SIGNUP_BONUS"])),
                "currency": config["CURRENCY"],
                "max_monthly_successful_referrals": config[
                    "REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS"
                ],
                "require_phone_verification": config["REFERRAL_REQUIRE_PHONE_VERIFICATION"],
            },
        )
        return program


class ReferralCode(BaseModel):
    """The code a user shares. One per user, and not theirs to choose.

    Random rather than sequential: a guessable code would let someone
    attribute their own sign-ups to a stranger, or enumerate the user base.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_code"
    )
    code = models.CharField(max_length=16, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "referrals_code"

    def __str__(self) -> str:
        return self.code

    @property
    def share_url(self) -> str:
        base = str(settings.VERIFYGH["FRONTEND_URL"]).rstrip("/")
        return f"{base}/register?ref={self.code}"


class Referral(BaseModel):
    """One referred user's attribution. Created during registration.

    `referred_user` is unique, so an account has exactly one referrer, for
    ever. There is no code path that reassigns it, and the database would
    refuse a second row anyway.
    """

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referrals_made"
    )
    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral"
    )
    code = models.CharField(max_length=16, db_index=True)

    status = models.CharField(
        max_length=16, choices=ReferralStatus.choices, default=ReferralStatus.PENDING,
        db_index=True,
    )
    #: Customer-safe explanation of the current status. Never a fraud signal.
    reason = models.CharField(max_length=255, blank=True, default="")
    #: Internal detail for staff, including why something was flagged.
    staff_note = models.CharField(max_length=500, blank=True, default="")

    signup_ip = models.GenericIPAddressField(null=True, blank=True)
    device_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)
    risk_score = models.PositiveSmallIntegerField(default=0)

    eligible_at = models.DateTimeField(null=True, blank=True)
    rewarded_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals_reviewed",
    )

    class Meta:
        db_table = "referrals_referral"
        ordering = ["-created_at"]
        constraints = [
            # Self-referral is impossible at the database level, not merely
            # checked in a service that someone could bypass later.
            models.CheckConstraint(
                check=~Q(referrer=F("referred_user")), name="referral_not_self"
            ),
            models.CheckConstraint(
                check=Q(status__in=[
                    "PENDING", "ELIGIBLE", "REWARDED", "REJECTED", "FRAUD_FLAGGED",
                ]),
                name="referral_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["referrer", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Referral<{self.code} {self.status}>"


class RewardStatus(models.TextChoices):
    ISSUED = "ISSUED", "Issued"
    REVERSED = "REVERSED", "Reversed"


class ReferralReward(BaseModel):
    """The promotional credit granted for a referral. One per referral, ever.

    `referral` is a OneToOne, so a second reward cannot be written even if two
    requests race past the service layer. `ledger_entry_id` points at the
    wallet ledger row that actually moved the credit - this table records the
    decision, the ledger records the money.
    """

    referral = models.OneToOneField(Referral, on_delete=models.PROTECT, related_name="reward")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_rewards"
    )
    reference = models.CharField(max_length=40, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="GHS")

    status = models.CharField(
        max_length=10, choices=RewardStatus.choices, default=RewardStatus.ISSUED, db_index=True
    )
    ledger_entry_id = models.UUIDField(null=True, blank=True, db_index=True)
    reversal_entry_id = models.UUIDField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referral_rewards_reversed",
    )

    class Meta:
        db_table = "referrals_reward"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gt=Decimal("0.00")), name="referral_reward_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.currency} {self.amount}"


class ReferralRiskFlag(BaseModel):
    """Why a referral was held, flagged or rejected. Staff-only.

    A flag is a reason to look, not a punishment: a shared IP address alone
    never rejects anything, because homes, offices, schools and mobile
    networks all share addresses in Ghana.
    """

    referral = models.ForeignKey(Referral, on_delete=models.CASCADE, related_name="risk_flags")
    kind = models.CharField(max_length=24, choices=RiskKind.choices, db_index=True)
    level = models.CharField(max_length=6, choices=RiskLevel.choices, default=RiskLevel.LOW)
    detail = models.CharField(max_length=255, blank=True, default="")
    #: True when this flag alone is enough to withhold the reward.
    blocking = models.BooleanField(default=False)

    class Meta:
        db_table = "referrals_risk_flag"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["referral", "kind"], name="referral_risk_flag_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} ({self.level})"
