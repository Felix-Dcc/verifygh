from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("verifygh.funding")


@shared_task(name="apps.funding.tasks.sync_provider_balances")
def sync_provider_balances() -> dict:
    """Beat: read every provider balance, grade it, and run the account checks."""
    from apps.funding import services

    return services.sync_all()


@shared_task(name="apps.funding.tasks.refresh_provider_balance")
def refresh_provider_balance(provider_id: str) -> str | None:
    """Read one provider's balance now - after it refused an order, say."""
    from apps.catalog.models import Provider
    from apps.funding import services

    provider = Provider.objects.filter(pk=provider_id).first()
    if provider is None:
        return None
    return services.sync_balance(provider).status


@shared_task(name="apps.funding.tasks.deliver_alert")
def deliver_alert(alert_id: str) -> int:
    from apps.funding import services
    from apps.funding.models import ProviderAlert

    alert = ProviderAlert.objects.select_related("provider").filter(pk=alert_id).first()
    if alert is None:
        return 0
    return services.deliver(alert)
