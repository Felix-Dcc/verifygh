"""Notification channel abstraction.

Email works today. SMS and WhatsApp are registered but have no backend wired up,
so `notify(..., channels=("SMS",))` records a SKIPPED delivery rather than
silently doing nothing. Adding a provider later means writing one class and
registering it - no caller changes.
"""

from __future__ import annotations

import abc
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

logger = logging.getLogger("verifygh.notifications")


class NotificationChannel(abc.ABC):
    key: str = "base"

    @abc.abstractmethod
    def send(self, *, user, title: str, body: str, template: str = "",
             context: dict | None = None) -> tuple[bool, str]:
        """Return (delivered, error_message)."""


class InAppChannel(NotificationChannel):
    """No-op sender: the Notification row itself is the delivery."""

    key = "IN_APP"

    def send(self, *, user, title, body, template="", context=None):
        return True, ""


class EmailChannel(NotificationChannel):
    key = "EMAIL"

    def send(self, *, user, title, body, template="", context=None):
        if not user.email:
            return False, "No email address on file."

        context = {
            "user": user,
            "full_name": user.full_name or "there",
            "title": title,
            "body": body,
            "brand": settings.VERIFYGH["BRAND_NAME"],
            "frontend_url": settings.VERIFYGH["FRONTEND_URL"],
            **(context or {}),
        }

        text_body = body
        if template:
            try:
                text_body = render_to_string(template, context)
            except TemplateDoesNotExist:
                logger.warning("email_template_missing", extra={"template": template})

        try:
            message = EmailMultiAlternatives(
                subject=f"{settings.VERIFYGH['BRAND_NAME']}: {title}",
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            message.send(fail_silently=False)
            return True, ""
        except Exception as exc:
            # A failed email must never fail the business operation that
            # triggered it; it is recorded and moved on from.
            logger.warning("email_send_failed", extra={"error": exc.__class__.__name__})
            return False, str(exc)[:255]


class UnconfiguredChannel(NotificationChannel):
    """Placeholder for SMS / WhatsApp until a provider is wired up."""

    def __init__(self, key: str):
        self.key = key

    def send(self, *, user, title, body, template="", context=None):
        logger.info("notification_channel_not_configured", extra={"channel": self.key})
        return False, f"The {self.key} channel is not configured."


_CHANNELS: dict[str, NotificationChannel] = {
    "IN_APP": InAppChannel(),
    "EMAIL": EmailChannel(),
    "SMS": UnconfiguredChannel("SMS"),
    "WHATSAPP": UnconfiguredChannel("WHATSAPP"),
}


def register_channel(channel: NotificationChannel) -> None:
    _CHANNELS[channel.key] = channel


def get_channel(key: str) -> NotificationChannel | None:
    return _CHANNELS.get(key)
