"""Scheduled referral work.

Most referrals are settled the moment the user verifies their email. This
sweep catches the rest: someone who verified while the programme was paused,
a referrer who was at their monthly cap, or a reward whose issuing failed
mid-flight. It is idempotent by construction - it re-runs the same evaluation
and the same reward path, both of which refuse to pay twice.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.referrals.models import Referral, ReferralStatus

logger = logging.getLogger("verifygh.referrals")

BATCH_SIZE = 200


@shared_task(name="apps.referrals.tasks.process_pending_referrals")
def process_pending_referrals(limit: int = BATCH_SIZE) -> dict:
    from apps.referrals.services import process_referral

    pending = (
        Referral.objects.filter(status__in=[ReferralStatus.PENDING, ReferralStatus.ELIGIBLE])
        .select_related("referrer", "referred_user")
        .order_by("created_at")[:limit]
    )

    rewarded = held = 0
    for referral in pending:
        try:
            result = process_referral(referral)
        except Exception:  # noqa: BLE001 - one bad referral must not stop the sweep
            logger.exception("referral_sweep_failed", extra={"referral_id": str(referral.pk)})
            continue
        if result.status == ReferralStatus.REWARDED:
            rewarded += 1
        else:
            held += 1

    # Inviters whose friend has become a paying customer, where the reward
    # did not go through at the moment the order completed.
    from apps.referrals.services import issue_referrer_reward

    inviters = 0
    owed = (
        Referral.objects.filter(status=ReferralStatus.REWARDED, referrer_reward__isnull=True)
        .select_related("referrer", "referred_user")
        .order_by("rewarded_at")[:limit]
    )
    for referral in owed:
        try:
            if issue_referrer_reward(referral) is not None:
                inviters += 1
        except Exception:  # noqa: BLE001 - one bad referral must not stop the sweep
            logger.exception("referrer_reward_sweep_failed",
                             extra={"referral_id": str(referral.pk)})

    if rewarded or inviters:
        logger.info("referral_sweep", extra={"rewarded": rewarded, "held": held,
                                             "inviters_rewarded": inviters})
    return {"rewarded": rewarded, "held": held, "inviters_rewarded": inviters,
            "at": timezone.now().isoformat()}
