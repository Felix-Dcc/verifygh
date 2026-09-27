from __future__ import annotations

import logging

from apps.notifications.channels import get_channel
from apps.notifications.models import Channel, DeliveryStatus, Notification

logger = logging.getLogger("verifygh.notifications")


def notify(user, *, event: str, title: str, body: str = "",
           channels: tuple[str, ...] = (Channel.IN_APP,), email_template: str = "",
           context: dict | None = None, metadata: dict | None = None,
           subject: str = "") -> list[Notification]:
    """Send a notification across one or more channels.

    Never raises. A notification failing is not a reason for a payment or an
    order to fail, so every delivery outcome is recorded on the row instead.

    `subject` overrides the email subject line for channels that have one;
    without it the email is subject-lined from `title`.
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
            user=user, title=title, body=body, template=email_template, context=context,
            subject=subject,
        )
        status = DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED
        Notification.objects.filter(pk=notification.pk).update(
            delivery_status=status,
            delivery_error=error[:255],
        )
        # Mirror onto the in-memory row as well. A queryset `update()` does not
        # touch the instance, so a caller that checks the returned object -
        # registration does, to decide whether the verification email actually
        # went out - would otherwise always read the default PENDING and
        # conclude the send had failed.
        notification.delivery_status = status
        notification.delivery_error = error[:255]
        created.append(notification)

    return created


def unread_count(user) -> int:
    return Notification.objects.filter(
        user=user, channel=Channel.IN_APP, read_at__isnull=True
    ).count()
