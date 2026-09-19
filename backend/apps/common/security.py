"""Security response headers, including the Content-Security-Policy.

Two different policies, because two very different things are served:

* **The API** returns JSON. It should never load a script, a style or an image,
  and should never be framed. `default-src 'none'` says exactly that, and costs
  nothing because there is nothing legitimate to break.
* **Django admin and the DRF browsable API** are real HTML pages that ship
  inline styles and inline scripts. They get a narrower-than-default policy
  rather than a perfect one, and are expected to be reachable only by staff -
  ideally behind network controls too.

The frontend has its own, stricter, nonce-based policy in
`frontend/src/middleware.ts`. This module protects what Django serves.
"""

from __future__ import annotations

from django.conf import settings

#: Paths that serve HTML rather than JSON.
HTML_PREFIXES = ("/django-admin/", "/static/")

API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# Django admin relies on inline styles and inline event handlers. Nonces would
# be better, but they cannot be applied to templates we do not own.
ADMIN_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)

PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), usb=(), "
    "xr-spatial-tracking=()"
)


class SecurityHeadersMiddleware:
    """Adds CSP and the related isolation headers to every response.

    Set unconditionally rather than only in production: a header that is only
    exercised in production is a header nobody has tested.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        is_html = request.path.startswith(HTML_PREFIXES)
        response.setdefault(
            "Content-Security-Policy", ADMIN_CSP if is_html else API_CSP
        )

        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # The API is read cross-origin by our own frontend, so it must not be
        # same-origin isolated; the CORS allowlist is what restricts it.
        response.setdefault("Cross-Origin-Resource-Policy", "cross-origin")

        # Nothing this API returns should ever be cached by a shared proxy:
        # responses are per-user and include balances and order state.
        if request.path.startswith("/api/"):
            response.setdefault("Cache-Control", "no-store, private")

        if not settings.DEBUG:
            response.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )

        return response
