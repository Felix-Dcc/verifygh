from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.notifications.tasks.deliver_staff_alert", ignore_result=True)
def deliver_staff_alert(**payload) -> int:
    """Send a staff alert (apps/notifications/staff.py) from the worker."""
    from apps.notifications.staff import deliver

    return deliver(**payload)
