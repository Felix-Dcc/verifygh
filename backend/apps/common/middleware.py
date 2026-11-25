"""Per-request context, client IP resolution and the Cloudflare origin lock."""

from __future__ import annotations

import contextvars
import hmac
import ipaddress
import json
import logging
import time
import uuid

logger = logging.getLogger("verifygh.edge")

_context: contextvars.ContextVar[dict] = contextvars.ContextVar("request_context", default={})


def get_request_context() -> dict:
    return _context.get()


#: Set by a Cloudflare Request Header Transform Rule to CLOUDFLARE_ORIGIN_SECRET
#: on every request it forwards (docs/CLOUDFLARE.md). Cloudflare overwrites any
#: value a visitor sends, so only traffic that passed through it can carry the
#: right one. Names starting cf- are reserved by Cloudflare, hence this name.
CLOUDFLARE_ORIGIN_META = "HTTP_X_VERIFYGH_ORIGIN"

#: The platform's health checks reach the container directly, never through
#: Cloudflare, and must never be refused. Railway sends its own Host; Render
#: sends the service's custom domain, so the health path is let through too.
RAILWAY_HEALTHCHECK_HOST = "healthcheck.railway.app"


def came_through_cloudflare(request) -> bool:
    """Whether this request provably passed through our Cloudflare zone."""
    from django.conf import settings

    if getattr(settings, "CLOUDFLARE_MODE", "off") == "off":
        return False
    secret = getattr(settings, "CLOUDFLARE_ORIGIN_SECRET", "") or ""
    given = request.META.get(CLOUDFLARE_ORIGIN_META, "") or ""
    return bool(secret and given) and hmac.compare_digest(given.encode(), secret.encode())


def _cloudflare_client_ip(request) -> str:
    """CF-Connecting-IP, but only on a request proven to come from Cloudflare.

    Cloudflare sends it "only on the traffic from Cloudflare's edge to your
    origin". Anyone reaching the origin directly could write it themselves, so
    it is believed only alongside the origin secret.
    """
    if not came_through_cloudflare(request):
        return ""
    value = (request.META.get("HTTP_CF_CONNECTING_IP", "") or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def get_client_ip(request) -> str:
    """The client's address, as far as it can be trusted.

    Behind Cloudflare (CLOUDFLARE_MODE report/enforce, request carrying the
    origin secret) that is CF-Connecting-IP. Otherwise it is read from
    X-Forwarded-For as below.

    X-Forwarded-For is written left to right: the client first, then each
    proxy appends the address it received from. Everything left of our own
    proxies is supplied by the client and can say anything, so the leftmost
    entry is exactly the wrong one to trust. We take the entry
    TRUSTED_PROXY_COUNT hops from the right, matching DRF's NUM_PROXIES.

    This value feeds audit logs, login telemetry, device fingerprints and rate
    limits - a forgeable IP would poison all four.
    """
    from django.conf import settings

    via_cloudflare = _cloudflare_client_ip(request)
    if via_cloudflare:
        return via_cloudflare

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


class CloudflareOriginMiddleware:
    """Only traffic that came through Cloudflare reaches the application.

    CLOUDFLARE_MODE:
      off     - nothing checked (the default, and the state before DNS moves).
      report  - requests without the origin secret are logged, not refused.
                Use it right after the DNS move to confirm every route carries
                the header before switching to enforce.
      enforce - requests without it get 403: the Railway addresses
                (*.up.railway.app) no longer bypass Cloudflare's WAF and bot
                protection, and CF-Connecting-IP cannot be forged.

    Platform health checks (/health/) are always let through.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponse

        mode = getattr(settings, "CLOUDFLARE_MODE", "off")
        if mode == "off" or came_through_cloudflare(request) or _is_railway_healthcheck(request):
            return self.get_response(request)

        logger.warning("request_not_via_cloudflare", extra={
            "mode": mode, "path": request.path[:120],
            "host": (request.META.get("HTTP_HOST", "") or "")[:80],
        })
        if mode != "enforce":
            return self.get_response(request)
        return HttpResponse(
            json.dumps({"error": {"code": "FORBIDDEN", "message": "Forbidden."}}),
            status=403, content_type="application/json",
        )


def _is_railway_healthcheck(request) -> bool:
    host = (request.META.get("HTTP_HOST", "") or "").split(":")[0].lower()
    # /health/ says only whether the database answers, so it is safe to expose.
    return host == RAILWAY_HEALTHCHECK_HOST or request.path in ("/health", "/health/")


def bind_user(user) -> None:
    """Called by the auth layer once the user is known."""
    context = dict(_context.get())
    context["user_id"] = str(getattr(user, "id", "-"))
    _context.set(context)
