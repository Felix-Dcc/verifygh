"""Phone numbers as customers read them in messages and emails."""

from __future__ import annotations

import re

_NANP = re.compile(r"\+1(\d{3})(\d{3})(\d{4})")


def display_phone(number: str | None) -> str:
    """"+12233631317" -> "+1 (223) 363-1317", as the website shows it.

    Only a US/Canada number in E.164 is regrouped. Anything else comes back
    exactly as stored: a number left as it is beats one grouped wrongly.
    """
    value = (number or "").strip()
    match = _NANP.fullmatch(value)
    if match is None:
        return value
    area, exchange, line = match.groups()
    return f"+1 ({area}) {exchange}-{line}"
