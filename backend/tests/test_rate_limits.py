"""Rate limiting, including the bypasses found in the pre-production audit."""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from apps.common.middleware import get_client_ip

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"


def attempt(api, email, **extra):
    return api.post(LOGIN, {"email": email, "password": "wrong-password-x"},
                    format="json", **extra)


def test_a_spoofed_forwarded_header_does_not_reset_the_login_limit(api, user):
    codes = [
        attempt(api, user.email, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code
        for i in range(12)
    ]
    assert 429 in codes


def test_credential_stuffing_from_one_address_is_throttled(api, db):
    """Many different accounts, one address: the per-IP bucket must catch it."""
    codes = [attempt(api, f"victim{i}@example.com").status_code for i in range(40)]
    assert codes.count(429) >= 5


def test_client_ip_ignores_the_forged_leftmost_hop(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="6.6.6.6, 41.66.1.20", REMOTE_ADDR="10.1.1.1"
    )
    # The client wrote 6.6.6.6; our load balancer appended the real 41.66.1.20.
    assert get_client_ip(request) == "41.66.1.20"


def test_with_no_trusted_proxy_the_header_is_ignored_entirely(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6", REMOTE_ADDR="10.1.1.1")
    assert get_client_ip(request) == "10.1.1.1"


def test_throttling_fails_open_when_the_cache_is_down(api, user, monkeypatch):
    """A Redis outage must not become an API outage."""
    from django.core.cache import cache

    def broken(*args, **kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(cache, "get", broken)

    response = api.post(LOGIN, {"email": user.email, "password": "Correct-Horse-Battery-1"},
                        format="json")
    assert response.status_code == 200


def test_account_lockout_still_protects_login_without_the_cache(api, user, settings, monkeypatch):
    """The reason failing open is acceptable: the lockout lives in the database."""
    from django.core.cache import cache

    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_FAILED_LOGINS": 3}
    monkeypatch.setattr(cache, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))

    for _ in range(3):
        attempt(api, user.email)

    response = api.post(LOGIN, {"email": user.email, "password": "Correct-Horse-Battery-1"},
                        format="json")
    assert response.status_code == 423
