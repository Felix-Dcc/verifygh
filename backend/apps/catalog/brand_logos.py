"""Official brand logos from Brandfetch, for services Simple Icons does not cover.

Staff match a service to its brand in Admin > Logos: the API searches
Brandfetch by the service's name (live, every time - Brandfetch's terms do not
allow search results to be stored), staff pick the right brand, and the
service's logo becomes that brand's icon on Brandfetch's CDN. Nothing is
matched automatically: a name like "Adams" or "Circle" belongs to many
companies, and a missing logo is better than someone else's.

Brandfetch's Logo API must be hotlinked: customers' browsers load the image
from cdn.brandfetch.io, and this server never downloads one (their terms, and
the site's CSP allows that one image origin). `fallback/404` means a brand with
no logo returns 404 - so the frontend shows its own generic tile, never a
made-up letter.

BRANDFETCH_CLIENT_ID comes from Brandfetch's developer portal. It travels in
every logo URL, so it is not a secret, but it lives in the environment only.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import requests
from django.conf import settings
from rest_framework import status

from apps.common.errors import APIError, ValidationFailed

logger = logging.getLogger("verifygh.catalog")

SEARCH_URL = "https://api.brandfetch.io/v2/search/{name}"
CDN = "https://cdn.brandfetch.io"
#: Square brand icon, 128px (sharp at the 64px the app draws at most), and a
#: 404 rather than a placeholder when the brand has none.
LOGO_PATH = "/domain/{domain}/w/128/h/128/type/icon/fallback/404"
MAX_CANDIDATES = 6

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
#: The only external logo URL a service may have: one this module built.
_LOGO_URL = re.compile(
    r"^https://cdn\.brandfetch\.io/domain/[a-z0-9.-]{4,253}/w/128/h/128/type/icon/fallback/404"
    r"\?c=[A-Za-z0-9_-]{6,64}$"
)


class BrandLogosUnavailable(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "BRAND_LOGOS_UNAVAILABLE"
    message = "Brand logo search is not available right now. Please try again in a few minutes."


class BrandLogosNotConfigured(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "BRAND_LOGOS_NOT_CONFIGURED"
    message = "Brand logos are not set up. Set BRANDFETCH_CLIENT_ID on the API, then reload."


@dataclass(frozen=True)
class Candidate:
    name: str
    domain: str
    claimed: bool

    def as_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain, "claimed": self.claimed,
                "logo_url": logo_url(self.domain)}


def client_id() -> str:
    value = (settings.BRANDFETCH_CLIENT_ID or "").strip()
    return value if _CLIENT_ID.match(value) else ""


def is_configured() -> bool:
    return bool(client_id())


def clean_domain(value: str) -> str:
    """ "https://www.Venmo.com/about" -> "venmo.com". Raises on anything else."""
    text = (value or "").strip().lower()
    if "://" in text:
        text = urlsplit(text).hostname or ""
    text = text.split("/")[0].split("?")[0].rstrip(".")
    if text.startswith("www."):
        text = text[4:]
    if not _DOMAIN.match(text):
        raise ValidationFailed("Enter the brand's website, like venmo.com.")
    return text


def logo_url(domain: str) -> str:
    """The brand's icon on Brandfetch's CDN, for an <img>."""
    if not is_configured():
        raise BrandLogosNotConfigured()
    return f"{CDN}{LOGO_PATH.format(domain=clean_domain(domain))}?c={client_id()}"


def is_brand_logo_url(value: str) -> bool:
    return bool(_LOGO_URL.match(value or ""))


def search(name: str) -> list[Candidate]:
    """Brands Brandfetch knows by this name, best first. Live; never stored."""
    if not is_configured():
        raise BrandLogosNotConfigured()
    query = (name or "").strip()[:80]
    if not query:
        return []
    try:
        response = requests.get(
            SEARCH_URL.format(name=quote(query, safe="")),
            params={"c": client_id()},
            timeout=8,
        )
    except requests.RequestException:
        logger.warning("brandfetch_search_unreachable")
        raise BrandLogosUnavailable() from None

    if response.status_code == 429:
        logger.warning("brandfetch_search_rate_limited")
        raise BrandLogosUnavailable(
            "Brandfetch is limiting searches right now. Wait a few minutes, then try again."
        )
    if response.status_code != 200:
        logger.warning("brandfetch_search_failed", extra={"status": response.status_code})
        raise BrandLogosUnavailable()
    try:
        rows = response.json()
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        raise BrandLogosUnavailable()

    found: list[Candidate] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            domain = clean_domain(str(row.get("domain") or ""))
        except ValidationFailed:
            continue
        if domain in seen:
            continue
        seen.add(domain)
        found.append(Candidate(
            name=str(row.get("name") or domain)[:120],
            domain=domain,
            claimed=row.get("claimed") is True,
        ))
        if len(found) >= MAX_CANDIDATES:
            break
    return found
