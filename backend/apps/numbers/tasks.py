from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("verifygh.numbers")

#: Beyond this the number is left for the provider's own expiry to release.
MAX_RELEASE_ATTEMPTS = 4


@shared_task(name="apps.numbers.tasks.release_turned_away_number")
def release_turned_away_number(usage_id: str, attempt: int = 1) -> bool:
    """Release a flagged number we declined, once the provider will let us.

    OnlineSim refuses to close an operation that has received no SMS until its
    protective interval has passed, so the first attempt is scheduled after it
    and a refusal is retried a few times before giving up. Giving up costs
    little: the operation expires upstream on its own.
    """
    from apps.numbers.models import NumberUsage
    from apps.verification.registry import get_provider

    usage = (
        NumberUsage.objects.select_related("order__provider", "order__service")
        .filter(pk=usage_id, released=False).first()
    )
    if usage is None:
        return True

    provider = get_provider(usage.order.provider.adapter_key)
    try:
        released = bool(provider.cancel_order(usage.provider_order_id))
    except Exception:
        logger.warning("number_release_retry_failed", extra={"usage": usage_id})
        released = False

    if released:
        NumberUsage.objects.filter(pk=usage.pk).update(released=True)
        return True

    if attempt < MAX_RELEASE_ATTEMPTS:
        release_turned_away_number.apply_async(
            args=[usage_id, attempt + 1],
            countdown=provider.release_retry_after_seconds(
                usage.order.provider_service_code or usage.order.service.slug
            ),
        )
    else:
        logger.warning("number_release_abandoned", extra={"usage": usage_id})
    return False


#: How often, and for how long, a failed report to the provider is retried.
REPORT_RETRY_SECONDS = 120
MAX_REPORT_ATTEMPTS = 5


@shared_task(name="apps.numbers.tasks.send_issue_to_provider")
def send_issue_to_provider(issue_id: str, attempt: int = 1) -> bool:
    """Send a customer's report to the provider as soon as it is filed.

    Straight away because the provider only takes reports within its own
    window; retried because a provider hiccup must not cost the customer their
    claim.
    """
    from apps.numbers.models import IssueStatus, VerificationIssue
    from apps.numbers.services import send_to_provider

    issue = (VerificationIssue.objects.select_related("order__provider")
             .filter(pk=issue_id, status=IssueStatus.AWAITING_PROVIDER).first())
    if issue is None:
        return True
    if send_to_provider(issue):
        return True
    if attempt < MAX_REPORT_ATTEMPTS:
        send_issue_to_provider.apply_async(args=[issue_id, attempt + 1],
                                           countdown=REPORT_RETRY_SECONDS * attempt)
    else:
        logger.warning("provider_issue_report_abandoned", extra={"issue": issue.reference})
    return False


@shared_task(name="apps.numbers.tasks.check_provider_refunds")
def check_provider_refunds(limit: int = 200) -> dict:
    """Refund customers whose reported verification the provider has refunded.

    Runs until each claim is settled - there is no deadline: a claim past its
    expected decision time stays open, and keeps being checked, until the
    provider refunds it or staff record the provider's refusal.
    """
    from apps.numbers.models import IssueStatus, VerificationIssue
    from apps.numbers.services import check_provider_decision

    waiting = (VerificationIssue.objects.select_related("order__provider")
               .filter(status=IssueStatus.AWAITING_PROVIDER)
               .order_by("provider_checked_at", "created_at")[:limit])
    checked = refunded = 0
    for issue in waiting:
        checked += 1
        try:
            if check_provider_decision(issue) == "REFUNDED":
                refunded += 1
        except Exception:
            # One case failing must not stop the others being checked.
            logger.exception("provider_refund_settle_failed", extra={"issue": issue.reference})
    if checked:
        logger.info("provider_refunds_checked", extra={"checked": checked, "refunded": refunded})
    return {"checked": checked, "refunded": refunded}
