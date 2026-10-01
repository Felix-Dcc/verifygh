"""Cloudflare Turnstile: the server half of the human check on sign-in and sign-up.

The browser solves Cloudflare's widget and receives a one-time token; this asks
Cloudflare whether that token is genuine, before any password is checked or any
account is created (Cloudflare's server-side validation:
https://developers.cloudflare.com/turnstile/get-started/server-side-validation/).
A token is single use and lasts five minutes, so the frontend fetches a fresh
one after every attempt.

Off while TURNSTILE_SECRET_KEY is unset - local development, and production
until the widget exists. Neither the secret nor a token is ever logged.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from rest_framework import status

from apps.common.errors import APIError
from apps.common.middleware import get_client_ip

logger = logging.getLogger("verifygh.auth")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

#: Cloudflare caps a token at 2048 characters; anything longer is not one.
MAX_TOKEN_LENGTH = 2048


class HumanCheckFailed(APIError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "HUMAN_CHECK_FAILED"
    message = "Please complete the security check and try again."


class HumanCheckUnavailable(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "HUMAN_CHECK_UNAVAILABLE"
    message = "We could not run the security check just now. Please try again in a moment."


def is_enabled() -> bool:
    return bool(settings.TURNSTILE_SECRET_KEY)


def require_human(request, token: str | None, *, action: str) -> None:
    """Raise unless Cloudflare confirms `token` was solved for `action`.

    Fails closed: if Cloudflare cannot be asked, nobody gets past - a check that
    opens whenever it is unreachable is a check an attacker can switch off.
    """
    if not is_enabled():
        return

    token = (token or "").strip() if isinstance(token, str) else ""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        _rejected(action, "missing")

    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    ip = get_client_ip(request)
    if ip:
        data["remoteip"] = ip

    try:
        response = requests.post(SITEVERIFY_URL, data=data, timeout=8)
        response.raise_for_status()
        outcome = response.json()
    except (requests.RequestException, ValueError):
        logger.warning("turnstile_unreachable", extra={"action": action})
        raise HumanCheckUnavailable() from None

    if not isinstance(outcome, dict) or outcome.get("success") is not True:
        codes = outcome.get("error-codes") if isinstance(outcome, dict) else None
        reason = ",".join(str(code)[:40] for code in (codes or [])[:4]) or "unsuccessful"
        _rejected(action, reason)

    # A token solved for one form is not good for another.
    solved_for = outcome.get("action") or ""
    if solved_for and solved_for != action:
        _rejected(action, "action_mismatch")

    allowed = settings.TURNSTILE_ALLOWED_HOSTNAMES
    if allowed and outcome.get("hostname") not in allowed:
        _rejected(action, "hostname_mismatch")


def _rejected(action: str, reason: str):
    logger.info("turnstile_rejected", extra={"action": action, "reason": reason})
    raise HumanCheckFailed()
