"""Ghanaian phone number normalisation.

Users type 024 123 4567, 0241234567, +233241234567 or 233241234567. All of them
are the same number; we store exactly one form (E.164) and display the local one.
"""

from __future__ import annotations

import re

from apps.accounts.constants import NETWORK_PREFIXES

COUNTRY_CODE = "233"
_DIGITS = re.compile(r"\D")


class InvalidPhoneNumber(ValueError):
    pass


def normalise_gh(raw: str) -> str:
    """Return E.164, e.g. +233241234567. Raises InvalidPhoneNumber otherwise."""
    if not raw:
        raise InvalidPhoneNumber("Enter your mobile money number.")
    digits = _DIGITS.sub("", str(raw))

    if digits.startswith("00233"):
        digits = digits[2:]
    if digits.startswith(COUNTRY_CODE) and len(digits) == 12:
        national = digits[3:]
    elif digits.startswith("0") and len(digits) == 10:
        national = digits[1:]
    elif len(digits) == 9:
        national = digits
    else:
        raise InvalidPhoneNumber("Enter a valid Ghanaian mobile number, e.g. 024 123 4567.")

    if len(national) != 9 or national[0] not in "2345":
        raise InvalidPhoneNumber("Enter a valid Ghanaian mobile number, e.g. 024 123 4567.")
    return f"+{COUNTRY_CODE}{national}"


def to_local(e164: str) -> str:
    """+233241234567 -> 0241234567"""
    digits = _DIGITS.sub("", e164 or "")
    if digits.startswith(COUNTRY_CODE):
        digits = digits[3:]
    return f"0{digits}" if digits else ""


def format_local(e164: str) -> str:
    """+233241234567 -> 024 123 4567"""
    local = to_local(e164)
    if len(local) != 10:
        return local
    return f"{local[:3]} {local[3:6]} {local[6:]}"


def detect_network(phone: str) -> str | None:
    """Infer the MoMo network from the prefix, or None if unrecognised."""
    local = to_local(normalise_gh(phone))
    prefix = local[:3]
    for network, prefixes in NETWORK_PREFIXES.items():
        if prefix in prefixes:
            return str(network)
    return None
