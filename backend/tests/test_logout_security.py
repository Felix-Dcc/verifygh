"""What must be true after a customer signs out.

Clearing cookies is the easy half, and `test_auth.py` already covers it. These
are the other half: the parts an attacker cares about, and the parts a customer
discovers by pressing the browser's Back button.

The question each test asks is the same one - after logging out, can anything
that was true before still be used? A cleared cookie only stops *this* browser
sending the token. If the token itself still works, a copy taken anywhere else
is a live session.
"""

from __future__ import annotations

import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db

LOGOUT = "/api/v1/auth/logout/"
REFRESH = "/api/v1/auth/refresh/"
ME = "/api/v1/auth/me/"
WALLET = "/api/v1/wallet/"
ORDERS = "/api/v1/orders/"


def cookies_of(response):
    return {name: morsel.value for name, morsel in response.cookies.items()}


# ---------------------------------------------------------------------------
# The session ends
# ---------------------------------------------------------------------------


def test_private_endpoints_reject_the_request_after_logout(api, user, auth):
    """The check that matters: it is enforced by the server, not the UI."""
    client = auth(user)
    assert client.get(ME).status_code == 200

    client.post(LOGOUT, {}, format="json")
    api.cookies.clear()
    api.credentials()

    for path in (ME, WALLET, ORDERS):
        assert api.get(path).status_code == 401, f"{path} still answered"


def test_the_refresh_token_cannot_mint_a_new_session_after_logout(api, user, auth):
    """The heart of it.

    Clearing a cookie only stops this browser sending the token. If the token
    still works, a copy taken from a shared machine - or from a backup, or over
    someone's shoulder - is a live session for as long as it has left to run.
    Logging out has to kill the token itself.
    """
    client = auth(user)
    stolen = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert stolen

    client.post(LOGOUT, {}, format="json")

    api.cookies.clear()
    api.credentials()
    response = api.post(REFRESH, {"refresh": stolen}, format="json")

    assert response.status_code == 401
    assert "access" not in response.data


def test_the_signed_out_sessions_own_access_token_stops_working(api, user, auth):
    """Found while writing this suite: it used to keep working for 20 minutes.

    Blacklisting the refresh token stops new sessions being minted, but the
    access token already issued was self-contained and nothing checked it
    against the sign-out. A copy lifted from a shared computer - or from
    devtools - kept authenticating until it expired on its own.
    """
    client = auth(user)
    own_access = api.cookies[settings.AUTH_COOKIE_ACCESS].value
    assert own_access

    client.post(LOGOUT, {}, format="json")

    api.cookies.clear()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {own_access}")
    assert api.get(ME).status_code == 401


def test_signing_out_one_device_leaves_the_others_signed_in(api, user, auth):
    """The reason this is a per-token denylist and not a token_version bump.

    Bumping the version would also have closed the gap above - by signing the
    customer out of their laptop because they tapped Log out on their phone.
    That is "sign out everywhere", a different action, and it already happens
    on a password change or reset.
    """
    from apps.accounts.authentication import issue_tokens

    laptop_access, _ = issue_tokens(user)

    phone = auth(user)
    phone.post(LOGOUT, {}, format="json")

    api.cookies.clear()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {laptop_access}")
    assert api.get(ME).status_code == 200, "logging out one device signed out another"


def test_a_bearer_client_can_sign_out_too(api, user):
    """Server-to-server and future app clients send the token in a header, not
    a cookie. Their sign-out has to revoke it all the same."""
    from apps.accounts.authentication import issue_tokens

    access, refresh = issue_tokens(user)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert api.get(ME).status_code == 200

    api.post(LOGOUT, {"refresh": refresh}, format="json")

    assert api.get(ME).status_code == 401


def test_logging_out_twice_is_not_an_error(api, user, auth):
    """A double-tap, or a retry on a flaky connection, must not look broken."""
    client = auth(user)

    first = client.post(LOGOUT, {}, format="json")
    second = client.post(LOGOUT, {}, format="json")

    assert first.status_code == 200
    assert second.status_code == 200


def test_logging_out_without_a_session_is_not_an_error(api):
    """Otherwise someone whose session already expired is stuck holding a
    cookie they cannot clear."""
    response = api.post(LOGOUT, {}, format="json")

    assert response.status_code == 200


def test_logging_out_with_a_garbage_refresh_token_still_succeeds(api, user, auth):
    client = auth(user)

    response = client.post(LOGOUT, {"refresh": "not-a-token"}, format="json")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# What logout must NOT do
# ---------------------------------------------------------------------------


def test_one_users_logout_does_not_end_another_users_session(api, user, other_user, auth):
    """Two customers on one device, or simply two accounts - signing one out
    must leave the other alone."""
    from rest_framework.test import APIClient

    from apps.accounts.authentication import issue_tokens

    second = APIClient()
    access, _ = issue_tokens(other_user)
    second.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert second.get(ME).status_code == 200

    auth(user).post(LOGOUT, {}, format="json")

    assert second.get(ME).status_code == 200, "logging one user out ended another's session"


def test_logout_does_not_touch_the_account(api, user, auth):
    """Signing out is not deactivating, and must not look like it."""
    client = auth(user)

    client.post(LOGOUT, {}, format="json")

    user.refresh_from_db()
    assert user.is_active is True
    assert user.is_suspended is False
    assert user.is_email_verified is True


def test_signing_back_in_works_immediately(api, user, auth):
    """A revoked session must not lock the customer out of making a new one."""
    client = auth(user)
    client.post(LOGOUT, {}, format="json")
    api.cookies.clear()
    api.credentials()

    response = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "Correct-Horse-Battery-1"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == user.email


def test_the_response_carries_nothing_sensitive(api, user, auth):
    """Whatever the browser keeps, it must not be a usable credential."""
    client = auth(user)

    response = client.post(LOGOUT, {}, format="json")

    body = str(response.data).lower()
    for leak in ("token", "secret", "password", "bearer"):
        assert leak not in body

    # The cookies are cleared rather than reissued with a value.
    for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
        assert response.cookies[name].value == ""
