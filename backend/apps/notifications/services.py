from __future__ import annotations

import logging

from apps.notifications.channels import get_channel
from apps.notifications.models import Channel, DeliveryStatus, Notification

logger = logging.getLogger("verifygh.notifications")


def notify(user, *, event: str, title: str, body: str = "",
           channels: tuple[str, ...] = (Channel.IN_APP,), email_template: str = "",
           context: dict | None = None, metadata: dict | None = None) -> list[Notification]:
    """Send a notification across one or more channels.

    Never raises. A notification failing is not a reason for a payment or an
    order to fail, so every delivery outcome is recorded on the row instead.
    """
    created: list[Notification] = []

    for channel_key in channels:
        try:
            notification = Notification.objects.create(
                user=user,
                event=event,
                title=title[:120],
                body=body[:400],
                channel=channel_key,
                metadata=metadata or {},
            )
        except Exception:
            logger.exception("notification_create_failed", extra={"event": event})
            continue

        channel = get_channel(str(channel_key))
        if channel is None:
            Notification.objects.filter(pk=notification.pk).update(
                delivery_status=DeliveryStatus.SKIPPED,
                delivery_error="Unknown channel.",
            )
            continue

        delivered, error = channel.send(
            user=user, title=title, body=body, template=email_template, context=context
        )
        Notification.objects.filter(pk=notification.pk).update(
            delivery_status=DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED,
            delivery_error=error[:255],
        )
        created.append(notification)

    return created


def unread_count(user) -> int:
    return Notification.objects.filter(
        user=user, channel=Channel.IN_APP, read_at__isnull=True
    ).count()
