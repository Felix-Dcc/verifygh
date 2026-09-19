"""Logs must be useful for debugging and useless to an attacker."""

from __future__ import annotations

import json
import logging

from apps.common.logging import JsonFormatter, RedactingFilter, mask_phone, redact_mapping


def render(message, *args, **extra):
    record = logging.LogRecord("verifygh.test", logging.INFO, __file__, 1, message, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    RedactingFilter().filter(record)
    return JsonFormatter().format(record)


def test_bearer_tokens_are_redacted_from_messages():
    line = render("upstream said Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
    assert "eyJhbGci" not in line


def test_paystack_keys_are_redacted():
    line = render("using key sk_live_4f8a9b2c7d1e6f3a0b")
    assert "4f8a9b2c7d1e6f3a0b" not in line
    assert "sk_live_" in line  # the prefix stays, so you know what was there


def test_verification_codes_in_structured_fields_are_redacted():
    line = render("order update", verification_code="457770", order="VGH-ABC123")
    payload = json.loads(line)
    assert "457770" not in line
    assert payload["order"] == "VGH-ABC123"  # non-sensitive context survives


def test_passwords_in_nested_payloads_are_redacted():
    cleaned = redact_mapping({"user": {"email": "a@b.c", "password": "hunter22"}})
    assert cleaned["user"]["password"] == "[REDACTED]"
    assert cleaned["user"]["email"] == "a@b.c"


def test_error_codes_stay_readable():
    """Redaction must not eat the thing you search logs for during an incident."""
    line = render("api_error", error_code="INSUFFICIENT_FUNDS")
    assert "INSUFFICIENT_FUNDS" in line


def test_phone_numbers_are_masked():
    assert mask_phone("+233241234567") == "233***4567"
    assert "1234567" not in mask_phone("0241234567")


def test_keys_that_merely_contain_a_sensitive_word_survive():
    line = render("req", status_code=502, country_code="GH", token_version=3)
    payload = json.loads(line)
    assert payload["status_code"] == 502
    assert payload["country_code"] == "GH"
    assert payload["token_version"] == 3


def test_whole_sensitive_keys_are_still_redacted():
    line = render("req", code="457770", token="abc.def.ghi", api_key="k_123456789")
    for secret in ("457770", "abc.def.ghi", "k_123456789"):
        assert secret not in line
