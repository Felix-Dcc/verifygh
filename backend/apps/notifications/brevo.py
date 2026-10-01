"""Transactional email through Brevo's API, as a Django email backend.

Every email the application sends already goes one way: `notify()` ->
`EmailChannel` -> Django's `EmailMultiAlternatives` -> EMAIL_BACKEND. This is
that last step for Brevo, so no caller knows or cares which provider sends -
there are no Brevo calls anywhere else in the project.

Brevo's documented transactional endpoint, not SMTP: `POST /v3/smtp/email`
with the `api-key` header (https://developers.brevo.com/reference/sendtransacemail).
HTTPS on 443 works from any host - SMTP ports are blocked on Railway - and an
answer comes back with a reason when Brevo refuses a message.

Failures raise `BrevoError`, whose message is written for staff and logs: it
names what went wrong (the key, the sender, the recipient, credits, a rate
limit) and never contains the API key. EmailChannel catches it, records it on
the notification and carries on: an email failing never fails the purchase,
payment or sign-up that triggered it, and no customer ever sees Brevo's words.
"""

from __future__ import annotations

import html
import logging
import re
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger("verifygh.notifications")

API_URL = "https://api.brevo.com/v3/smtp/email"

#: Brevo caps sender and recipient display names at 70 characters.
NAME_LIMIT = 70

_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class BrevoError(Exception):
    """Brevo did not accept a message. `retryable` when trying later may work."""

    def __init__(self, message: str, *, code: str = "", status: int | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


def _mask(text: str) -> str:
    """An address in Brevo's answer stays out of the log."""
    return _EMAIL_IN_TEXT.sub("<address>", text)


def _explain(status: int, code: str, detail: str) -> tuple[str, bool]:
    """(what went wrong, for staff; whether a retry may succeed)."""
    lowered = f"{code} {detail}".lower()
    if status == 401 or code == "unauthorized":
        return ("Brevo refused the API key - it is wrong or revoked, or Brevo is blocking "
                "this server's IP address (Brevo > Security > Authorised IPs).", False)
    if status == 402 or code == "not_enough_credits":
        return "The Brevo account has no email credits left.", False
    if status == 429:
        return "Brevo is rate-limiting sends; it will be tried again.", True
    if status >= 500:
        return f"Brevo had a server error ({status}); it will be tried again.", True
    if "sender" in lowered:
        return (f"Brevo refused the sender - the address or its domain is not verified in "
                f"Brevo ({_mask(detail)[:160]}).", False)
    if status == 403:
        return f"Brevo refused the request ({_mask(detail)[:160]}).", False
    return f"Brevo refused the email: {code or status} - {_mask(detail)[:160]}.", False


def text_to_html(text: str) -> str:
    """Brevo needs an HTML part. A plain-text message gets the simplest honest one."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    body = "".join(
        f"<p>{html.escape(p.strip()).replace(chr(10), '<br>')}</p>" for p in paragraphs
    )
    return f"<!DOCTYPE html><html><body>{body or '<p></p>'}</body></html>"


class BrevoEmailBackend(BaseEmailBackend):
    """Sends `EmailMessage`s through Brevo. Configured by BREVO_API_KEY."""

    def __init__(self, fail_silently: bool = False, api_key: str | None = None,
                 timeout: int | None = None, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = (api_key if api_key is not None
                        else getattr(settings, "BREVO_API_KEY", "")) or ""
        self.timeout = timeout or getattr(settings, "EMAIL_TIMEOUT", 10) or 10
        self.session: requests.Session | None = None

    def open(self):
        if self.session is None:
            self.session = requests.Session()
            return True
        return False

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        if not self.api_key:
            if self.fail_silently:
                return 0
            raise BrevoError("Brevo is not configured: BREVO_API_KEY is empty.",
                             code="not_configured")
        opened = self.open()
        sent = 0
        try:
            for message in email_messages:
                try:
                    self._send(message)
                    sent += 1
                except BrevoError:
                    if not self.fail_silently:
                        raise
        finally:
            if opened:
                self.close()
        return sent

    # -- one message ---------------------------------------------------------

    def _payload(self, message) -> dict:
        sender_name, sender_email = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
        if not sender_email or "@" not in sender_email:
            raise BrevoError("The sender address is not set (BREVO_SENDER_EMAIL).",
                             code="no_sender")
        if message.attachments:
            # Nothing in VerifyGH attaches files; refusing beats sending half.
            raise BrevoError("Attachments are not supported by this backend.",
                             code="attachments")

        def people(addresses):
            out = []
            for address in addresses or []:
                name, email = parseaddr(address)
                if not _EMAIL_IN_TEXT.fullmatch(email or ""):
                    # Caught here, not by Brevo: no call is spent on it.
                    raise BrevoError("A recipient address is not valid.", code="invalid_recipient")
                out.append({"email": email, **({"name": name[:NAME_LIMIT]} if name else {})})
            return out

        html_part = next((content for content, mimetype in getattr(message, "alternatives", [])
                          if mimetype == "text/html"), None)
        if getattr(message, "content_subtype", "plain") == "html":
            html_part, text_part = message.body, None
        else:
            text_part = message.body

        payload = {
            "sender": {"email": sender_email,
                       **({"name": sender_name[:NAME_LIMIT]} if sender_name else {})},
            "to": people(message.to),
            "subject": message.subject,
            "htmlContent": html_part or text_to_html(text_part or ""),
        }
        if text_part:
            payload["textContent"] = text_part
        if message.cc:
            payload["cc"] = people(message.cc)
        if message.bcc:
            payload["bcc"] = people(message.bcc)
        if message.reply_to:
            reply = people(message.reply_to[:1])
            if reply:
                payload["replyTo"] = reply[0]
        if not payload["to"]:
            raise BrevoError("The email has no recipient.", code="no_recipient")
        return payload

    def _send(self, message) -> None:
        payload = self._payload(message)
        session = self.session or requests.Session()
        try:
            response = session.post(
                API_URL, json=payload, timeout=self.timeout,
                headers={"api-key": self.api_key, "accept": "application/json"},
            )
        except requests.Timeout:
            raise BrevoError("Brevo did not answer in time; it will be tried again.",
                             code="timeout", retryable=True) from None
        except requests.RequestException as exc:
            raise BrevoError(f"Could not reach Brevo ({exc.__class__.__name__}); it will be "
                             "tried again.", code="network", retryable=True) from None

        if response.status_code in (200, 201, 202):
            try:
                message_id = str((response.json() or {}).get("messageId", ""))[:120]
            except ValueError:
                message_id = ""
            logger.info("brevo_email_accepted", extra={"message_id": message_id})
            return

        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code", "") if isinstance(body, dict) else "")[:60]
        detail = str(body.get("message", "") if isinstance(body, dict) else "")[:300]
        explanation, retryable = _explain(response.status_code, code, detail)
        logger.warning("brevo_email_refused", extra={
            "status": response.status_code, "code": code, "detail": _mask(detail)[:200],
        })
        raise BrevoError(explanation, code=code or f"http_{response.status_code}",
                         status=response.status_code, retryable=retryable)
