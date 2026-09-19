from __future__ import annotations

import logging

from celery import shared_task

from apps.catalog.services import sync_catalog

logger = logging.getLogger("verifygh.catalog")


@shared_task(name="apps.catalog.tasks.sync_provider_catalog")
def sync_provider_catalog(adapter_key: str | None = None) -> dict:
    """Refresh services, countries, costs and availability from the provider."""
    return sync_catalog(adapter_key)
