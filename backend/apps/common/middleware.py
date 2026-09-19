"""Per-request context: a request id that threads through every log line."""

from __future__ import annotations

import contextvars
import time
import uuid

_context: contextvars.ContextVar[dict] = contextvars.ContextVar("request_context", default={})


def get_request_context() -> dict:
    return _context.get()


def get_client_ip(request) -> str:
    """The client's address, as far as it can be trusted.

    X-Forwarded-For is written left to right: the client first, then each
    proxy appends the address it received from. Everything left of our own
    proxies is supplied by the client and can say anything, so the leftmost
    entry is exactly the wrong one to trust. We take the entry
    TRUSTED_PROXY_COUNT hops from the right, matching DRF's NUM_PROXIES.

    This value feeds audit logs, login telemetry, device fingerprints and rate
    limits - a forgeable IP would poison all four.
    """
    from django.conf import settings

    remote_addr = request.META.get("REMOTE_ADDR", "") or ""
    proxies = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if proxies <= 0 or not forwarded:
        return remote_addr

    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if not hops:
        return remote_addr
    return hops[-min(proxies, len(hops))]


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex[:16]
        request.request_id = request_id
        request.client_ip = get_client_ip(request)
        token = _context.set({"request_id": request_id, "user_id": "-"})
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            _context.reset(token)
        response["X-Request-ID"] = request_id
        response["X-Response-Time-ms"] = f"{(time.monotonic() - started) * 1000:.0f}"
        return response


def bind_user(user) -> None:
    """Called by the auth layer once the user is known."""
    context = dict(_context.get())
    context["user_id"] = str(getattr(user, "id", "-"))
    _context.set(context)
