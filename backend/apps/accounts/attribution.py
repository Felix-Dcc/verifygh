"""Where a new account came from: the campaign link or site that sent it.

The browser remembers the first campaign link (``utm_*`` parameters) or
outside site a visitor arrived from, and sends it with the sign-up. It is
recorded on the AUTH_REGISTER audit entry so marketing can count sign-ups -
and, through them, deposits and orders - per channel.

Nothing here is trusted or required. A visitor can send anything, so every
value is cut to a short, plain token and anything else is dropped; a sign-up
never fails because of it. It holds no personal data: a channel name, a
campaign name, the page they landed on and the referring site's host name.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: The fields kept, as the browser sends them. ``landing`` is a path on our
#: site; ``referrer`` is the host name of the site that linked to us.
FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "landing", "referrer")

MAX_LENGTH = 64
_SAFE = re.compile(r"[^a-z0-9._\-/]")


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower().replace(" ", "_")
    # Drop a query string or fragment: a landing path never needs one, and it
    # is where anything personal would be.
    value = value.split("?", 1)[0].split("#", 1)[0]
    return _SAFE.sub("", value)[:MAX_LENGTH]


def clean_attribution(raw: Any) -> dict[str, str]:
    """The recognised, non-empty fields of ``raw``, each made safe to store."""
    if not isinstance(raw, Mapping):
        return {}
    cleaned = {key: _clean(raw.get(key)) for key in FIELDS}
    return {key: value for key, value in cleaned.items() if value}
