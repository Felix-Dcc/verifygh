"""How well-known services are presented: a clean name, what else people call
them, a category, and whether staff count them as popular.

Providers name things for themselves - OnlineSim lists "TikTok (TikTok)" and
"Twitter|X" - and supply no categories at all, so this is ours. It is applied
when a sync first creates a service, and was backfilled onto existing rows by
catalog migration 0004. After that the database is the source of truth: staff
can change any of it from the admin, and a sync never overwrites it.

`popular` is a rank (lower first) or None. Only services the connected provider
actually offers ever appear - an entry here for a service nobody sells is
inert.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from apps.catalog.models import ServiceCategory as C

#: slug -> (display name, aliases, category, popular rank or None)
PRESENTATION: dict[str, tuple[str, str, str, int | None]] = {
    "tiktok": ("TikTok", "tik tok", C.SOCIAL, 1),
    "whatsapp": ("WhatsApp", "whats app", C.MESSAGING, 2),
    "telegram": ("Telegram", "", C.MESSAGING, 3),
    "google": ("Google / Gmail", "gmail, youtube", C.EMAIL, 4),
    "facebook": ("Facebook", "fb, meta", C.SOCIAL, 5),
    # OnlineSim's code for Facebook is a number.
    "3223": ("Facebook", "fb, meta", C.SOCIAL, 5),
    "instagram": ("Instagram", "ig, insta", C.SOCIAL, 6),
    "discord": ("Discord", "", C.MESSAGING, 7),
    "signal": ("Signal", "", C.MESSAGING, 8),
    "twitter": ("X (Twitter)", "x, twitter", C.SOCIAL, 9),
    "x": ("X (Twitter)", "x, twitter", C.SOCIAL, 9),
    "snapchat": ("Snapchat", "snap", C.SOCIAL, None),
    "tinder": ("Tinder", "", C.SOCIAL, None),
    "linkedin": ("LinkedIn", "", C.BUSINESS, None),
    "openai": ("ChatGPT / OpenAI", "chatgpt, openai", C.DEVELOPER, None),
    "microsoft": ("Microsoft / Outlook", "outlook, hotmail, live", C.EMAIL, None),
    "yahoo": ("Yahoo", "yahoo mail", C.EMAIL, None),
    "apple": ("Apple", "icloud, apple id", C.OTHER, None),
    "amazon": ("Amazon", "", C.SHOPPING, None),
    "steam": ("Steam", "", C.GAMING, None),
    "netflix": ("Netflix", "", C.OTHER, None),
    "uber": ("Uber", "", C.OTHER, None),
    "paypal": ("PayPal", "", C.FINANCE, None),
}


_ICON_FILE = Path(__file__).with_name("service_icons.json")
_icons: dict[str, str] | None = None


def logo_key(text: str) -> str:
    """Brand key: "Wells Fargo" -> "wellsfargo", "AT&T" -> "atandt"."""
    text = (text or "").lower().replace("&", "and").replace("+", "plus")
    return re.sub(r"[^a-z0-9]", "", text)


def bundled_icon_url(slug: str, name: str = "") -> str:
    """The bundled logo for a service, or "" when none is bundled.

    By our slug first (each checked by hand), then by the service's name or id
    as a brand key - which is how a service the sync has not added yet picks
    up its mark the day it arrives. Exact keys only: never a nearest match.
    """
    global _icons
    if _icons is None:
        _icons = json.loads(_ICON_FILE.read_text(encoding="utf-8"))["icons"]
    for key in (slug, logo_key(slug), logo_key(name)):
        if key and key in _icons:
            return f"/service-icons/{key}.svg"
    return ""
