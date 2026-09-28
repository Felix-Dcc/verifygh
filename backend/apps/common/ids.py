"""Human-facing reference generators.

Short, unambiguous, and safe to read aloud over the phone to support: the
alphabet excludes I, O, 0 and 1 so support never has to guess.
"""

from __future__ import annotations

import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _token(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def order_reference() -> str:
    return f"VGH-{_token(6)}"


def payment_reference() -> str:
    return f"VGH-PAY-{_token(8)}"


def ledger_reference() -> str:
    return f"VGH-TXN-{_token(8)}"


def refund_reference() -> str:
    return f"VGH-RFD-{_token(6)}"


def issue_reference() -> str:
    return f"VGH-ISS-{_token(6)}"
