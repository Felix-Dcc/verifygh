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
