"""Structured logging with hard redaction.

Two rules this module enforces:
  1. Nothing that looks like a credential is ever written to a log.
  2. Verification codes and full phone numbers are never written to a log.
"""

from __future__ import annotations

import json
import logging
import re

SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "access", "refresh", "authorization",
    "api_key", "apikey", "api_secret", "secret_key", "private_key", "signature",
    "otp", "code", "verification_code", "pin", "cvv", "card", "account_number",
}

_PATTERNS = [
    # Bearer / api keys in free text
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(sk_(?:live|test)_)[A-Za-z0-9]+"), r"\1[REDACTED]"),
    # Our own admin API keys: keep the public prefix, never the secret.
    (re.compile(r"(vgh_ak_[0-9a-f]{8}_)[A-Za-z0-9_\-]+"), r"\1[REDACTED]"),
    # A JWT anywhere in free text - an exception message, a repr, a URL.
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED_JWT]"),
    # Full phone numbers: E.164 (+233..., and the foreign numbers we rent out)
    # and Ghanaian local format. The first digits and last four survive, as
    # with mask_phone, so support can still correlate.
    (re.compile(r"(?<![\w+])(\+\d{3})\d{3,8}(\d{4})(?!\d)"), r"\1***\2"),
    (re.compile(r"(?<![\w.])(0[235]\d)\d{3}(\d{4})(?!\w)"), r"\1***\2"),
    # key=value / "key": "value" for sensitive keys. The lookbehind makes the
    # key match whole: without it "code" also matched error_code, status_code
    # and country_code, and "token" matched token_version - scrubbing exactly
    # the fields you search for during an incident.
    (re.compile(
        r'(?i)((?<![A-Za-z0-9_])"?(?:' + "|".join(SENSITIVE_KEYS) + r')"?\s*[:=]\s*"?)'
        r'([^\s",}]+)'
    ), r"\1[REDACTED]"),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(data):
    """Recursively redact a dict/list before it is logged or stored."""
    if isinstance(data, dict):
        return {
            key: ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact_mapping(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_mapping(item) for item in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


def mask_phone(phone: str | None) -> str:
    """0241234567 -> 024***4567. Enough to identify, not enough to reuse."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 7:
        return "*" * len(digits)
    return f"{digits[:3]}***{digits[-4:]}"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(str(record.msg))
            if isinstance(record.args, dict):
                record.args = redact_mapping(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_mapping(arg) for arg in record.args)
        except Exception:  # never let logging break a request
            pass
        return True


class RequestContextFilter(logging.Filter):
    """Attaches the current request id / user id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        from apps.common.middleware import get_request_context

        context = get_request_context()
        record.request_id = getattr(record, "request_id", None) or context.get("request_id", "-")
        record.user_id = getattr(record, "user_id", None) or context.get("user_id", "-")
        return True


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime", "message", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact_text(json.dumps(payload, default=str))
