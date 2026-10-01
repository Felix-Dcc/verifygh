"""Telling staff when something needs a person: an order that did not go through,
a customer's report about a number.

Each alert is an in-app notification (the bell in the admin) and an email, to
every active staff member whose role carries the permission to act on it.
Delivered from the worker after the transaction commits, so a slow mail server
never holds up a customer's purchase or report - and an alert is never sent
for something that was rolled back.

A burst of failures (a provider outage) must not become a burst of emails: an
alert can name a cooldown, and within it only the in-app notification is
sent - the email that did go out says to check the admin for more.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger("verifygh.notifications")


def staff_with(permission: str):
    """Active, unsuspended staff whose role grants `permission`."""
    from apps.accounts.constants import ROLE_PERMISSIONS
    from apps.accounts.models import User

    roles = [role for role, granted in ROLE_PERMISSIONS.items() if str(permission) in granted]
    return User.objects.filter(role__in=roles, is_active=True, is_suspended=False)


def alert_staff(*, permission: str, event: str, title: str, body: str, link: str,
                reference: str, email: bool = True, cooldown_key: str = "",
                cooldown_seconds: int = 0) -> None:
    """Queue an alert for after the current transaction commits."""
    payload = {
        "permission": str(permission), "event": event, "title": title[:120],
        "body": body[:400], "link": link, "reference": reference, "email": email,
        "cooldown_key": cooldown_key, "cooldown_seconds": cooldown_seconds,
    }

    def _queue():
        from apps.notifications.tasks import deliver_staff_alert

        try:
            deliver_staff_alert.delay(**payload)
        except Exception:
            # No broker: deliver in-process rather than lose the alert.
            logger.warning("staff_alert_queue_unavailable", extra={"event": event})
            deliver(**payload)

    transaction.on_commit(_queue)


def deliver(*, permission: str, event: str, title: str, body: str, link: str,
            reference: str, email: bool, cooldown_key: str, cooldown_seconds: int) -> int:
    """Notify every recipient. Returns how many were notified. Never raises."""
    from apps.notifications.models import Channel
    from apps.notifications.services import notify

    channels = [Channel.IN_APP]
    if email:
        # cache.add is atomic: of two failures at the same moment, one emails.
        if not cooldown_key or cache.add(cooldown_key, 1, cooldown_seconds):
            channels.append(Channel.EMAIL)

    sent = 0
    for user in staff_with(permission):
        notify(
            user, event=event, title=title, body=body, channels=tuple(channels),
            subject=f"[VerifyGH] {title}",
            metadata={"admin_link": link, "reference": reference},
        )
        sent += 1
    logger.info("staff_alert_sent", extra={"event": event, "reference": reference,
                                           "recipients": sent,
                                           "emailed": Channel.EMAIL in channels})
    return sent
