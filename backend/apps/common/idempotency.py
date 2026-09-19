"""Idempotency key helpers.

Idempotency here is never "check then act" in Python — it is always a unique
constraint in the database. These helpers only normalise and derive keys.
"""

from __future__ import annotations

import hashlib
import re
import uuid

_SAFE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")


def normalise(key: str | None) -> str | None:
    if not key:
        return None
    key = key.strip()
    return key if _SAFE.match(key) else None


def generate() -> str:
    return uuid.uuid4().hex


def derive(*parts: str) -> str:
    """Deterministic key from stable inputs (e.g. provider + external event id)."""
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:64]


def from_request(request) -> str:
    """Prefer the client's key so retries collapse; fall back to a fresh one."""
    header = normalise(request.headers.get("X-Idempotency-Key"))
    if header:
        return header
    body_key = None
    if isinstance(getattr(request, "data", None), dict):
        body_key = normalise(request.data.get("idempotency_key"))
    return body_key or generate()
