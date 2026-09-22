"""Referral attribution, eligibility and reward issuance.

The reward is money, so it follows the same rules as every other money path in
this project: the ledger is the only writer, the operation is idempotent by
database constraint, and the decision is made here - never by the browser.

Reward issuance is safe to call from anywhere, any number of times, and
concurrently. Three independent things make a second reward impossible:

1. `SELECT ... FOR UPDATE` on the referral row (PostgreSQL),
2. `ReferralReward.referral` is a OneToOne,
3. the ledger entry's idempotency key is derived from the referral id.

Any one of them alone would be enough; together they hold on SQLite too, where
there are no row locks.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.common.errors import Conflict, ValidationFailed
from apps.common.ids import ALPHABET
from apps.common.money import ZERO, quantize
from apps.referrals.models import (
    Referral,
    ReferralCode,
    ReferralProgram,
    ReferralReward,
    ReferralRiskFlag,
    ReferralStatus,
    RewardStatus,
    RiskKind,
    RiskLevel,
)
from apps.wallet.models import FundType, LedgerDirection, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import credit_referral_bonus, get_or_create_wallet

logger = logging.getLogger("verifygh.referrals")

CODE_PREFIX = "VGH"
CODE_BODY_LENGTH = 5
MAX_CODE_ATTEMPTS = 8


# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------


def normalize_code(raw: str | None) -> str:
    """Codes are case-insensitive and whitespace-tolerant; stored upper-case."""
    return (raw or "").strip().upper().replace(" ", "")[:16]


def _new_code() -> str:
    # ALPHABET excludes I, O, 0 and 1, so a code read aloud or copied from a
    # WhatsApp message cannot become a different valid code.
    body = "".join(secrets.choice(ALPHABET) for _ in range(CODE_BODY_LENGTH))
    return f"{CODE_PREFIX}{body}"


def code_for(user) -> ReferralCode:
    """The user's referral code, created on first use. Never regenerated."""
    existing = ReferralCode.objects.filter(user=user).first()
    if existing is not None:
        return existing

    for _ in range(MAX_CODE_ATTEMPTS):
        try:
            with transaction.atomic():
                return ReferralCode.objects.create(user=user, code=_new_code())
        except IntegrityError:
            # Either the code collided (retry with a new one) or another
            # request created this user's code first (return theirs).
            existing = ReferralCode.objects.filter(user=user).first()
            if existing is not None:
                return existing
            continue
    raise Conflict("We could not create a referral code. Please try again.")


def resolve_code(raw: str | None):
    """The user behind a code, or None. Never reveals anything about them."""
    code = normalize_code(raw)
    if not code:
        return None
    entry = (
        ReferralCode.objects.select_related("user")
        .filter(code=code, is_active=True)
        .first()
    )
    if entry is None or entry.user.is_suspended or not entry.user.is_active:
        return None
    return entry


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def attach_referral(*, new_user, raw_code: str | None, request=None) -> Referral | None:
    """Record who referred `new_user`. Called once, inside registration.

    Runs the cheap anti-abuse checks immediately so the evidence is captured
    while we have the request, but never awards anything here: eligibility is
    decided later, after verification.
    """
    program = ReferralProgram.load()
    if not program.is_enabled:
        return None

    entry = resolve_code(raw_code)
    if entry is None:
        # An unknown or inactive code is simply ignored - registration
        # continues normally, and we tell the caller nothing about why.
        return None
    if entry.user_id == new_user.id:
        return None

    from apps.accounts.models import UserDevice
    from apps.common.middleware import get_client_ip

    ip = get_client_ip(request) if request is not None else None
    fingerprint = ""
    if request is not None:
        fingerprint = UserDevice.fingerprint(
            request.META.get("HTTP_USER_AGENT", "")[:300], ip or ""
        )

    try:
        # Savepoint: losing the race on UNIQUE(referred_user) is an expected
        # outcome here, and must not poison the caller's transaction - this
        # runs inside registration.
        with transaction.atomic():
            referral = Referral.objects.create(
                referrer=entry.user,
                referred_user=new_user,
                code=entry.code,
                signup_ip=ip or None,
                device_fingerprint=fingerprint,
            )
    except IntegrityError:
        # This account already has a referrer. It keeps the first one.
        logger.info("referral_attribution_duplicate", extra={"user_id": str(new_user.pk)})
        return Referral.objects.filter(referred_user=new_user).first()

    _record_signup_risk(referral, new_user=new_user, referrer=entry.user, ip=ip,
                        fingerprint=fingerprint)
    logger.info(
        "referral_attributed",
        extra={"referral_id": str(referral.pk), "referrer_id": str(entry.user_id)},
    )
    return referral


def _flag(referral: Referral, kind: str, level: str, detail: str, *, blocking: bool) -> None:
    ReferralRiskFlag.objects.get_or_create(
        referral=referral, kind=kind,
        defaults={"level": level, "detail": detail[:255], "blocking": blocking},
    )


def _record_signup_risk(referral: Referral, *, new_user, referrer, ip, fingerprint) -> None:
    """Capture what we can see at sign-up. Flags describe; they do not punish."""
    from apps.accounts.models import UserDevice

    if new_user.email and new_user.email.lower() == (referrer.email or "").lower():
        _flag(referral, RiskKind.SHARED_EMAIL, RiskLevel.HIGH,
              "Referred account uses the referrer's email address.", blocking=True)

    if new_user.phone and new_user.phone == referrer.phone:
        _flag(referral, RiskKind.SHARED_PHONE, RiskLevel.HIGH,
              "Referred account uses the referrer's phone number.", blocking=True)

    if fingerprint and UserDevice.objects.filter(
        user=referrer, fingerprint_hash=fingerprint
    ).exists():
        # Same browser and IP as the referrer. A household might share a
        # laptop, so this holds the reward for review instead of rejecting it.
        _flag(referral, RiskKind.SHARED_DEVICE, RiskLevel.HIGH,
              "Referred account signed up on the referrer's device.", blocking=True)

    if ip and referrer.signup_ip and ip == referrer.signup_ip:
        # Never blocking on its own: homes, offices, schools, hostels and
        # mobile networks in Ghana all put many people behind one address.
        _flag(referral, RiskKind.SHARED_IP, RiskLevel.LOW,
              "Referrer and referred user share a sign-up IP address.", blocking=False)

    if fingerprint:
        others = (
            UserDevice.objects.filter(fingerprint_hash=fingerprint)
            .exclude(user=new_user)
            .exclude(user=referrer)
            .count()
        )
        if others >= 2:
            _flag(referral, RiskKind.DUPLICATE_ACCOUNT, RiskLevel.MEDIUM,
                  f"This device is already used by {others} other accounts.", blocking=True)

    recent = Referral.objects.filter(
        referrer=referrer, created_at__gte=timezone.now() - timedelta(hours=1)
    ).exclude(pk=referral.pk).count()
    program = ReferralProgram.load()
    if recent >= program.velocity_per_hour:
        _flag(referral, RiskKind.REFERRER_VELOCITY, RiskLevel.MEDIUM,
              f"{recent + 1} sign-ups from this referrer within an hour.", blocking=True)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


class Decision:
    """The outcome of evaluating one referral."""

    def __init__(self, status: str, reason: str = "", staff_note: str = ""):
        self.status = status
        self.reason = reason
        self.staff_note = staff_note

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Decision({self.status}, {self.reason!r})"


def has_received_signup_bonus(user) -> bool:
    """One signup bonus per account, whoever referred them.

    Checked against the ledger as well as the reward table, so a bonus granted
    by any means still counts.
    """
    if ReferralReward.objects.filter(user=user, status=RewardStatus.ISSUED).exists():
        return True
    return WalletLedgerEntry.objects.filter(
        wallet__user=user,
        entry_type=LedgerEntryType.REFERRAL_BONUS,
        direction=LedgerDirection.CREDIT,
    ).exists()


def monthly_reward_count(referrer) -> int:
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Referral.objects.filter(
        referrer=referrer, status=ReferralStatus.REWARDED, rewarded_at__gte=start
    ).count()


def evaluate(referral: Referral) -> Decision:
    """Decide whether this referral may be rewarded.

    Order matters: the cheapest and least ambiguous checks first, so a normal
    user waiting on email verification is never told anything about fraud.
    """
    program = ReferralProgram.load()
    referred = referral.referred_user
    referrer = referral.referrer

    if referral.status in (ReferralStatus.REWARDED, ReferralStatus.REJECTED):
        return Decision(referral.status, referral.reason)

    if not program.is_enabled:
        return Decision(ReferralStatus.PENDING, "The referral programme is paused.")

    # 8. Referrer and referred user are not the same account.
    if referrer.id == referred.id:
        return Decision(ReferralStatus.REJECTED, "A referral cannot be self-made.",
                        "Self-referral.")

    # 4. Neither account is suspended.
    if referred.is_suspended or not referred.is_active:
        return Decision(ReferralStatus.REJECTED, "This account is not active.",
                        "Referred account suspended or inactive.")
    if referrer.is_suspended or not referrer.is_active:
        return Decision(ReferralStatus.REJECTED,
                        "The inviting account is no longer active.",
                        "Referrer suspended or inactive.")

    # 2. Email verification completed.
    if program.require_email_verification and not referred.is_email_verified:
        return Decision(ReferralStatus.PENDING, "Verify your email address to qualify.")

    # 3. Phone verification, where the programme requires it.
    if program.require_phone_verification and not referred.is_phone_verified:
        return Decision(ReferralStatus.PENDING, "Verify your phone number to qualify.")

    # 7. The referred user has not already had a signup bonus.
    if has_received_signup_bonus(referred):
        _flag(referral, RiskKind.ALREADY_BONUSED, RiskLevel.MEDIUM,
              "This account already received a referral signup bonus.", blocking=True)
        return Decision(ReferralStatus.REJECTED,
                        "This account has already received a welcome bonus.",
                        "Duplicate signup bonus.")

    # 9. Anti-abuse: anything blocking goes to a human, not to a rejection.
    blocking = list(referral.risk_flags.filter(blocking=True))
    if blocking:
        kinds = ", ".join(flag.kind for flag in blocking)
        return Decision(ReferralStatus.FRAUD_FLAGGED,
                        "We are reviewing this invitation.",
                        f"Blocking risk flags: {kinds}")

    # Referrer's monthly cap. Held, not rejected: next month it qualifies.
    cap = program.max_monthly_successful_referrals
    if cap and monthly_reward_count(referrer) >= cap:
        _flag(referral, RiskKind.MONTHLY_LIMIT, RiskLevel.LOW,
              f"Referrer reached the monthly limit of {cap}.", blocking=False)
        return Decision(ReferralStatus.PENDING,
                        "This invitation is queued and will be reviewed shortly.",
                        f"Referrer at monthly cap of {cap}.")

    return Decision(ReferralStatus.ELIGIBLE, "Ready for your bonus.")


# ---------------------------------------------------------------------------
# Reward
# ---------------------------------------------------------------------------


def _lock_referral(referral_id) -> Referral:
    queryset = Referral.objects.filter(pk=referral_id).select_related(
        "referrer", "referred_user"
    )
    if connection.features.has_select_for_update:
        queryset = queryset.select_for_update()
    return queryset.get()


def issue_reward(referral: Referral, *, actor=None, force: bool = False) -> ReferralReward | None:
    """Grant the promotional credit. Atomic, idempotent, safe to race.

    Returns the reward (existing or new), or None if the referral is not
    eligible. `force` is for an admin overriding a held referral; it still
    cannot produce a second reward.
    """
    program = ReferralProgram.load()
    amount = quantize(program.signup_bonus)
    if amount <= ZERO:
        return None

    existing = ReferralReward.objects.filter(referral=referral).first()
    if existing is not None:
        return existing

    with transaction.atomic():
        locked = _lock_referral(referral.pk)

        # Re-read under the lock: another request may have rewarded it while
        # we were queuing for the row.
        already = ReferralReward.objects.filter(referral=locked).first()
        if already is not None:
            return already

        if not force:
            decision = evaluate(locked)
            if decision.status != ReferralStatus.ELIGIBLE:
                _apply_decision(locked, decision)
                return None
        if not force and has_received_signup_bonus(locked.referred_user):
            return None

        wallet = get_or_create_wallet(locked.referred_user)
        reference = _reward_reference()
        try:
            reward = ReferralReward.objects.create(
                referral=locked,
                user=locked.referred_user,
                reference=reference,
                amount=amount,
                currency=program.currency,
            )
        except IntegrityError:
            # Lost the race on the OneToOne. The winner's reward is the reward.
            return ReferralReward.objects.filter(referral=locked).first()

        entry = credit_referral_bonus(
            wallet=wallet,
            amount=amount,
            # Derived from the referral, so even a caller that skipped every
            # check above cannot post a second credit for it.
            idempotency_key=f"referral:{locked.pk}",
            referral_id=locked.pk,
            reward_reference=reference,
        )
        ReferralReward.objects.filter(pk=reward.pk).update(ledger_entry_id=entry.id)

        Referral.objects.filter(pk=locked.pk).update(
            status=ReferralStatus.REWARDED,
            reason="Bonus credited.",
            rewarded_at=timezone.now(),
            eligible_at=locked.eligible_at or timezone.now(),
            reviewed_by=actor,
        )

    logger.info(
        "referral_rewarded",
        extra={"referral_id": str(referral.pk), "reference": reference, "amount": str(amount)},
    )
    _notify_rewarded(referral, amount)
    reward.refresh_from_db()
    return reward


def _reward_reference() -> str:
    return "VGH-REF-" + "".join(secrets.choice(ALPHABET) for _ in range(8))


def _notify_rewarded(referral: Referral, amount) -> None:
    from apps.common.money import format_ghs
    from apps.notifications.services import notify

    def _send():
        notify(
            referral.referred_user,
            event="REFERRAL_BONUS",
            title="Your welcome bonus is here",
            body=(f"{format_ghs(amount)} of promotional credit has been added to your wallet. "
                  "Spend it on any verification - it is not withdrawable."),
            channels=("IN_APP",),
            metadata={"referral_id": str(referral.pk)},
        )

    transaction.on_commit(_send)


def _apply_decision(referral: Referral, decision: Decision) -> None:
    updates = {
        "status": decision.status,
        "reason": decision.reason[:255],
        "staff_note": decision.staff_note[:500],
    }
    if decision.status == ReferralStatus.ELIGIBLE and referral.eligible_at is None:
        updates["eligible_at"] = timezone.now()
    if decision.status == ReferralStatus.REJECTED and referral.rejected_at is None:
        updates["rejected_at"] = timezone.now()
    Referral.objects.filter(pk=referral.pk).update(**updates)


def process_referral(referral: Referral, *, actor=None) -> Referral:
    """Evaluate one referral and reward it if it qualifies."""
    decision = evaluate(referral)
    _apply_decision(referral, decision)
    if decision.status == ReferralStatus.ELIGIBLE:
        issue_reward(referral, actor=actor)
    referral.refresh_from_db()
    return referral


def process_for_user(user) -> Referral | None:
    """Called after the events that can make a referral eligible.

    Safe to call on every verification, sign-in or admin change: a rewarded or
    rejected referral is left alone, and a pending one is simply re-checked.
    """
    referral = Referral.objects.filter(referred_user=user).select_related(
        "referrer", "referred_user"
    ).first()
    if referral is None or referral.status in (
        ReferralStatus.REWARDED, ReferralStatus.REJECTED
    ):
        return referral
    return process_referral(referral)


def reverse_reward(reward: ReferralReward, *, admin, reason: str) -> ReferralReward:
    """Claw back promotional credit that should not have been granted.

    Debits whatever promotional credit remains. If the user already spent it,
    the balance is taken to zero and the shortfall is recorded - we never
    reach into their cash to recover promotional credit we issued.
    """
    if not reason or not reason.strip():
        raise ValidationFailed("A reason is required to reverse a referral reward.")
    if reward.status == RewardStatus.REVERSED:
        return reward

    from apps.wallet.services import post_entry

    with transaction.atomic():
        wallet = get_or_create_wallet(reward.user)
        wallet.refresh_from_db(fields=["promo_balance"])
        recoverable = min(quantize(wallet.promo_balance), quantize(reward.amount))
        entry = None
        if recoverable > ZERO:
            entry = post_entry(
                wallet=wallet,
                amount=recoverable,
                entry_type=LedgerEntryType.REVERSAL,
                direction=LedgerDirection.DEBIT,
                idempotency_key=f"referral-reversal:{reward.pk}",
                description=f"Referral bonus reversed: {reason.strip()[:120]}",
                counterparty=f"ADMIN:{admin.pk}",
                metadata={"referral_id": str(reward.referral_id), "reason": reason.strip()[:300]},
                created_by=admin,
                funds=FundType.PROMO,
                allow_frozen=True,
            )
        ReferralReward.objects.filter(pk=reward.pk).update(
            status=RewardStatus.REVERSED,
            reversal_entry_id=getattr(entry, "id", None),
            reversed_at=timezone.now(),
            reversed_by=admin,
        )
        Referral.objects.filter(pk=reward.referral_id).update(
            status=ReferralStatus.REJECTED,
            reason="This bonus was withdrawn.",
            staff_note=f"Reward reversed: {reason.strip()[:400]}",
            rejected_at=timezone.now(),
            reviewed_by=admin,
        )

    logger.warning(
        "referral_reward_reversed",
        extra={"reward_id": str(reward.pk), "recovered": str(recoverable)},
    )
    reward.refresh_from_db()
    return reward


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def stats_for(user) -> dict:
    """What the user sees on Refer & Earn. No fraud signals leak out here."""
    referrals = Referral.objects.filter(referrer=user)
    counts = {status: 0 for status, _ in ReferralStatus.choices}
    for row in referrals.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]

    rewarded = counts[ReferralStatus.REWARDED]
    issued = ReferralReward.objects.filter(
        referral__referrer=user, status=RewardStatus.ISSUED
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return {
        "successful": rewarded,
        # Anything still in play reads as pending to the referrer. A flagged
        # referral is under review, which is not something to advertise.
        "pending": counts[ReferralStatus.PENDING] + counts[ReferralStatus.ELIGIBLE]
        + counts[ReferralStatus.FRAUD_FLAGGED],
        "rejected": counts[ReferralStatus.REJECTED],
        "total": referrals.count(),
        "rewards_issued": str(quantize(issued)),
    }
