"""VerifyGH behind Cloudflare: real client IPs, and an origin only Cloudflare can reach.

Cloudflare sends the visitor's address in CF-Connecting-IP. Anyone reaching
the Railway origin directly could write that header too, so it is believed
only on requests carrying the origin secret that Cloudflare's Transform Rule
sets (X-VerifyGH-Origin). docs/CLOUDFLARE.md has the rollout.
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.common.middleware import get_client_ip
from apps.common.throttling import LoginIPThrottle

pytestmark = pytest.mark.django_db

SECRET = "s3cret-origin-value-that-is-long-enough-0123"
EDGE = "172.70.1.1"  # a Cloudflare edge address, as Railway sees it


@pytest.fixture
def cloudflare(settings):
    def _mode(mode: str):
        settings.CLOUDFLARE_MODE = mode
        settings.CLOUDFLARE_ORIGIN_SECRET = SECRET
        settings.TRUSTED_PROXY_COUNT = 1
    return _mode


def via_edge(client_ip: str, secret: str | None = SECRET, **extra) -> dict:
    """Headers as Railway receives a request Cloudflare forwarded."""
    headers = {
        "REMOTE_ADDR": "10.0.0.2",
        # Cloudflare appends the visitor; Railway's edge appends Cloudflare.
        "HTTP_X_FORWARDED_FOR": f"{client_ip}, {EDGE}",
        "HTTP_CF_CONNECTING_IP": client_ip,
        **extra,
    }
    if secret is not None:
        headers["HTTP_X_VERIFYGH_ORIGIN"] = secret
    return headers


def request_with(**meta):
    request = RequestFactory().get("/")
    request.META.update(meta)
    return request


# ---------------------------------------------------------------------------
# Client IP
# ---------------------------------------------------------------------------


def test_off_changes_nothing(cloudflare):
    cloudflare("off")
    # Today's behaviour: one trusted proxy (Railway), CF headers ignored.
    assert get_client_ip(request_with(**via_edge("203.0.113.9"))) == EDGE


@pytest.mark.parametrize("mode", ["report", "enforce"])
def test_behind_cloudflare_the_visitor_ip_is_used(cloudflare, mode):
    cloudflare(mode)
    assert get_client_ip(request_with(**via_edge("203.0.113.9"))) == "203.0.113.9"
    assert get_client_ip(request_with(**via_edge("2001:db8::7"))) == "2001:db8::7"


def test_a_forged_cf_header_without_the_secret_is_ignored(cloudflare):
    """Straight to the Railway origin, claiming to be someone else."""
    cloudflare("report")
    forged = {"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "198.51.100.66",
              "HTTP_CF_CONNECTING_IP": "203.0.113.9"}
    assert get_client_ip(request_with(**forged)) == "198.51.100.66"
    wrong = via_edge("203.0.113.9", secret="not-the-secret")
    assert get_client_ip(request_with(**wrong)) == EDGE


def test_a_malformed_cf_ip_falls_back(cloudflare):
    cloudflare("enforce")
    bad = via_edge("203.0.113.9", HTTP_CF_CONNECTING_IP="not-an-ip, 1.2.3.4")
    assert get_client_ip(request_with(**bad)) == EDGE


def test_rate_limits_key_on_the_visitor_not_the_edge(cloudflare):
    cloudflare("enforce")
    throttle = LoginIPThrottle()
    alice = request_with(**via_edge("203.0.113.9"))
    bob = request_with(**via_edge("203.0.113.10"))
    assert throttle.get_ident(alice) == "203.0.113.9"
    assert throttle.get_ident(bob) == "203.0.113.10"


def test_customers_behind_one_edge_do_not_share_a_bucket(cloudflare):
    """Password reset allows 5 an hour per IP. Two people, one Cloudflare edge."""
    cloudflare("enforce")
    client = APIClient()
    for _ in range(5):
        assert client.post("/api/v1/auth/password/reset/", {"email": "a@example.com"},
                           format="json", **via_edge("203.0.113.9")).status_code != 429
    assert client.post("/api/v1/auth/password/reset/", {"email": "a@example.com"},
                       format="json", **via_edge("203.0.113.9")).status_code == 429
    # Someone else on the same edge is unaffected.
    assert client.post("/api/v1/auth/password/reset/", {"email": "b@example.com"},
                       format="json", **via_edge("203.0.113.10")).status_code != 429


# ---------------------------------------------------------------------------
# The origin lock
# ---------------------------------------------------------------------------


def test_enforce_refuses_what_did_not_come_through_cloudflare(cloudflare, catalog):
    cloudflare("enforce")
    client = APIClient()

    direct = client.get("/api/v1/marketplace/", REMOTE_ADDR="198.51.100.66")
    assert direct.status_code == 403
    assert direct.json() == {"error": {"code": "FORBIDDEN", "message": "Forbidden."}}
    wrong = client.get("/api/v1/marketplace/", **via_edge("203.0.113.9", secret="guess"))
    assert wrong.status_code == 403

    assert client.get("/api/v1/marketplace/", **via_edge("203.0.113.9")).status_code == 200


def test_railway_health_checks_always_get_through(cloudflare, settings):
    cloudflare("enforce")
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "healthcheck.railway.app"]
    response = APIClient().get("/health/", HTTP_HOST="healthcheck.railway.app")
    assert response.status_code == 200


def test_render_health_checks_on_the_custom_domain_get_through(cloudflare, catalog):
    # Render's health check uses the custom domain and never passes Cloudflare.
    cloudflare("enforce")
    client = APIClient()
    assert client.get("/health/", REMOTE_ADDR="198.51.100.66").status_code == 200
    assert client.get("/api/v1/marketplace/", REMOTE_ADDR="198.51.100.66").status_code == 403


def test_report_logs_but_refuses_nothing(cloudflare, catalog, monkeypatch):
    from apps.common import middleware

    logged: list[str] = []
    monkeypatch.setattr(middleware.logger, "warning", lambda event, **_: logged.append(event))
    cloudflare("report")

    response = APIClient().get("/api/v1/marketplace/", REMOTE_ADDR="198.51.100.66")

    assert response.status_code == 200
    assert logged == ["request_not_via_cloudflare"]


def test_signed_webhooks_through_cloudflare_record_the_senders_ip(cloudflare, settings):
    """Paystack/TextVerified webhooks are verified by signature, not IP - but the
    recorded address should be theirs, not Cloudflare's."""
    from apps.payments.models import PaymentWebhookEvent

    cloudflare("enforce")
    settings.VERIFYGH = {**settings.VERIFYGH, "WEBHOOK_PROVIDERS": ["mock"]}
    APIClient().post("/api/v1/payments/webhooks/mock/", data=b"{}",
                     content_type="application/json", **via_edge("52.31.139.75"))
    event = PaymentWebhookEvent.objects.order_by("-created_at").first()
    assert event is not None  # recorded even when the signature is rejected
    assert event.remote_ip == "52.31.139.75"
