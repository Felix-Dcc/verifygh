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
             context: dict | None = None, subject: str = "") -> tuple[bool, str]:
        """Return (delivered, error_message)."""


class InAppChannel(NotificationChannel):
    """No-op sender: the Notification row itself is the delivery."""

    key = "IN_APP"

    def send(self, *, user, title, body, template="", context=None, subject=""):
        return True, ""


class EmailChannel(NotificationChannel):
    """Sends through whatever EMAIL_BACKEND is configured - Resend in production.

    Every message goes out as multipart: a plain-text body, plus an HTML
    alternative when a matching `.html` template exists. Text is the source of
    truth, so a message is never empty in a client that refuses HTML.
    """

    key = "EMAIL"

    def send(self, *, user, title, body, template="", context=None, subject=""):
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

        html_body = ""
        if template:
            html_template = template.rsplit(".", 1)[0] + ".html"
            try:
                html_body = render_to_string(html_template, context)
            except TemplateDoesNotExist:
                # Plain text only. Not an error - most messages do not need it.
                pass

        try:
            message = EmailMultiAlternatives(
                # An explicit subject wins, so a transactional email can say
                # what it is ("Verify your VerifyGH email address") instead of
                # wearing the in-app notification's title.
                subject=subject or f"{settings.VERIFYGH['BRAND_NAME']}: {title}",
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            if html_body:
                message.attach_alternative(html_body, "text/html")
            sent = message.send(fail_silently=False)
        except Exception as exc:
            # A failed email must never fail the business operation that
            # triggered it; it is recorded and moved on from.
            #
            # The class name and the provider's own message are logged, never
            # the message body, the recipient's address or the SMTP password.
            logger.warning(
                "email_send_failed",
                extra={
                    "user_id": str(getattr(user, "pk", "")),
                    "template": template or "-",
                    "error": exc.__class__.__name__,
                    "detail": str(exc)[:200],
                },
            )
            return False, str(exc)[:255]

        if not sent:
            # The backend accepted the call and delivered nothing. Recording
            # this as sent is how a broken mailer stays invisible.
            logger.warning(
                "email_not_accepted",
                extra={"user_id": str(getattr(user, "pk", "")), "template": template or "-"},
            )
            return False, "The mail server accepted no recipients."

        logger.info(
            "email_sent",
            extra={
                "user_id": str(getattr(user, "pk", "")),
                "template": template or "-",
                "backend": settings.EMAIL_BACKEND.rsplit(".", 2)[-2:][0],
            },
        )
        return True, ""


class UnconfiguredChannel(NotificationChannel):
    """Placeholder for SMS / WhatsApp until a provider is wired up."""

    def __init__(self, key: str):
        self.key = key

    def send(self, *, user, title, body, template="", context=None, subject=""):
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
