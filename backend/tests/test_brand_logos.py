"""Official brand logos from Brandfetch: the queue, live search, and the decision.

Brandfetch is never called: `requests.get` in the module is replaced, and what
it was asked is checked as carefully as what it answered.
"""

from __future__ import annotations

import pytest
import requests
from rest_framework.test import APIClient

from apps.audit.models import AdminAction
from apps.catalog import brand_logos
from apps.catalog.models import Service

pytestmark = pytest.mark.django_db

CLIENT_ID = "testClientId123"
QUEUE = "/api/v1/admin/services/logo-queue/"


def candidates(slug):
    return f"/api/v1/admin/services/{slug}/logo-candidates/"


def decide(slug):
    return f"/api/v1/admin/services/{slug}/brand-logo/"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture
def brandfetch(settings, monkeypatch):
    settings.BRANDFETCH_CLIENT_ID = CLIENT_ID
    calls = []

    def install(reply):
        def fake_get(url, params=None, timeout=None):
            calls.append({"url": url, "params": params, "timeout": timeout})
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(brand_logos.requests, "get", fake_get)
        return calls

    return install


@pytest.fixture
def staff(admin_user):
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": admin_user.email,
                                                    "password": "Correct-Horse-Battery-3"},
                           format="json")
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def unbranded(catalog):
    """A service on sale with no logo of any kind."""
    service = Service.objects.get(slug="linkedin")
    assert service.icon_url == ""
    return service


def test_the_logo_url_is_the_hotlinked_cdn_icon_with_a_404_fallback(settings):
    settings.BRANDFETCH_CLIENT_ID = CLIENT_ID
    url = brand_logos.logo_url("https://www.Venmo.com/about")
    assert url == ("https://cdn.brandfetch.io/domain/venmo.com/w/128/h/128/type/icon/fallback/404"
                   f"?c={CLIENT_ID}")
    assert brand_logos.is_brand_logo_url(url)
    # Anything else at that host is not ours to set.
    assert not brand_logos.is_brand_logo_url("https://cdn.brandfetch.io/domain/x.com?c=abc123")
    assert not brand_logos.is_brand_logo_url("https://evil.example/domain/venmo.com/w/128")


@pytest.mark.parametrize("value", ["", "venmo", "not a domain.com", "javascript:alert(1)",
                                   "http://", "a.b"])
def test_only_real_domains_are_accepted(value):
    from apps.common.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        brand_logos.clean_domain(value)


def test_the_queue_lists_services_on_sale_with_no_logo(staff, unbranded, brandfetch):
    body = staff.get(QUEUE).data
    assert body["configured"] is True
    slugs = [row["slug"] for row in body["results"]]
    assert "linkedin" in slugs
    # Already branded (bundled Simple Icons tile): not in the queue.
    assert "tiktok" not in slugs


def test_candidates_are_searched_live_by_the_service_name(staff, unbranded, brandfetch):
    calls = brandfetch(FakeResponse([
        {"name": "LinkedIn", "domain": "linkedin.com", "claimed": True, "brandId": "id1",
         "icon": "https://cdn.brandfetch.io/x"},
        {"name": "LinkedIn Learning", "domain": "https://learning.linkedin.com", "claimed": False},
        {"name": "Duplicate", "domain": "linkedin.com"},
        {"name": "Broken", "domain": "not a domain"},
    ]))
    body = staff.get(candidates("linkedin")).data

    (call,) = calls
    assert call["url"] == "https://api.brandfetch.io/v2/search/LinkedIn"
    assert call["params"] == {"c": CLIENT_ID}
    assert call["timeout"]
    assert [row["domain"] for row in body["results"]] == ["linkedin.com", "learning.linkedin.com"]
    assert body["results"][0]["claimed"] is True
    assert body["results"][0]["logo_url"].startswith("https://cdn.brandfetch.io/domain/linkedin.com/")


def test_a_different_search_term_can_be_tried(staff, unbranded, brandfetch):
    calls = brandfetch(FakeResponse([]))
    staff.get(candidates("linkedin"), {"q": "LinkedIn Learning"})
    assert calls[0]["url"].endswith("/v2/search/LinkedIn%20Learning")


def test_brandfetch_limits_and_outages_are_reported_not_hidden(staff, unbranded, brandfetch):
    brandfetch(FakeResponse({"message": "quota_exceeded"}, 429))
    response = staff.get(candidates("linkedin"))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "BRAND_LOGOS_UNAVAILABLE"

    brandfetch(requests.ConnectionError("down"))
    assert staff.get(candidates("linkedin")).status_code == 503


def test_without_a_client_id_nothing_is_searched(staff, unbranded, settings):
    settings.BRANDFETCH_CLIENT_ID = ""
    assert staff.get(QUEUE).data["configured"] is False
    response = staff.get(candidates("linkedin"))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "BRAND_LOGOS_NOT_CONFIGURED"


def test_choosing_a_brand_sets_its_logo_and_is_audited(staff, unbranded, brandfetch, api):
    response = staff.post(decide("linkedin"), {"domain": "www.linkedin.com"}, format="json")
    assert response.status_code == 200, response.data
    unbranded.refresh_from_db()
    assert unbranded.logo_domain == "linkedin.com"
    assert unbranded.icon_url == brand_logos.logo_url("linkedin.com")
    assert unbranded.logo_reviewed_at is not None
    assert AdminAction.objects.filter(action="SERVICE_LOGO_BRAND").exists()
    # Customers see it, and the service has left the queue.
    rows = api.get("/api/v1/marketplace/", {"country": "US", "search": "linkedin"}).data["results"]
    assert any(row["icon_url"] == unbranded.icon_url for row in rows)
    assert "linkedin" not in [row["slug"] for row in staff.get(QUEUE).data["results"]]


def test_no_match_leaves_the_generic_tile_and_leaves_the_queue(staff, unbranded, brandfetch):
    response = staff.post(decide("linkedin"), {"none": True}, format="json")
    assert response.status_code == 200
    unbranded.refresh_from_db()
    assert unbranded.icon_url == "" and unbranded.logo_reviewed_at is not None
    assert "linkedin" not in [row["slug"] for row in staff.get(QUEUE).data["results"]]


def test_a_decision_can_be_undone(staff, unbranded, brandfetch):
    staff.post(decide("linkedin"), {"domain": "linkedin.com"}, format="json")
    response = staff.delete(decide("linkedin"))
    assert response.status_code == 200
    unbranded.refresh_from_db()
    assert unbranded.icon_url == "" and unbranded.logo_domain == ""
    assert unbranded.logo_reviewed_at is None
    assert "linkedin" in [row["slug"] for row in staff.get(QUEUE).data["results"]]


def test_an_arbitrary_domain_string_cannot_inject_a_url(staff, unbranded, brandfetch):
    response = staff.post(decide("linkedin"), {"domain": "evil.example/x?c=1#"}, format="json")
    # The path and query are dropped; only a bare hostname is ever used.
    assert response.status_code == 200
    unbranded.refresh_from_db()
    assert unbranded.icon_url == brand_logos.logo_url("evil.example")


def test_staff_can_set_only_a_url_this_module_built(staff, unbranded, settings):
    settings.BRANDFETCH_CLIENT_ID = CLIENT_ID
    ok = staff.patch("/api/v1/admin/services/linkedin/",
                     {"icon_url": brand_logos.logo_url("linkedin.com")}, format="json")
    assert ok.status_code == 200, ok.data
    bad = staff.patch("/api/v1/admin/services/linkedin/",
                      {"icon_url": "https://cdn.brandfetch.io/anything.png"}, format="json")
    assert bad.status_code == 400


def test_support_staff_cannot_use_the_logo_queue(support_user, catalog, brandfetch):
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": support_user.email,
                                                    "password": "Correct-Horse-Battery-4"},
                           format="json")
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    assert client.get(QUEUE).status_code == 403
    assert client.post(decide("linkedin"), {"domain": "linkedin.com"},
                       format="json").status_code == 403
