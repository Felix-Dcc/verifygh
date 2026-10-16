"""Regression tests for the open items of the October 2026 audit (docs/AUDIT-2026-10.md).

A-09  logout and refresh accepted cross-site form posts
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
LOGOUT = "/api/v1/auth/logout/"
REFRESH = "/api/v1/auth/refresh/"


# ---------------------------------------------------------------------------
# A-09: refresh and logout refuse cross-site form posts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [LOGOUT, REFRESH])
@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded",
                                          "multipart/form-data; boundary=x", "text/plain"])
def test_a_cross_site_form_post_cannot_sign_the_visitor_out_or_rotate_them(
        user, auth, url, content_type):
    client = auth(user)
    response = client.post(url, "", content_type=content_type)

    assert response.status_code == 415
    assert "vgh_access" not in response.cookies
    # The session the form tried to end or rotate still works.
    assert client.get(ME).status_code == 200


def test_the_frontends_json_sign_out_still_works(user, auth):
    client = auth(user)
    response = client.post(LOGOUT, {}, format="json")

    assert response.status_code == 200
    assert client.get(ME).status_code == 401


def test_the_frontends_json_refresh_still_works(user, auth):
    client = auth(user)
    response = client.post(REFRESH, "{}", content_type="application/json")

    assert response.status_code == 200
    assert response.cookies["vgh_access"].value
