"""The human check on sign-in and sign-up, and signing in with Google.

Neither Cloudflare nor Google is called: `requests.post` is replaced in each
module, and what it was asked is checked as carefully as what it answered.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from django.conf import settings as django_settings
from django.core import signing

from apps.accounts import google as google_module
from apps.accounts import turnstile as turnstile_module
from apps.accounts.constants import Role
from apps.accounts.models import LoginAttempt, User

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
REGISTER = "/api/v1/auth/register/"
OPTIONS = "/api/v1/auth/sign-in-options/"
START = "/api/v1/auth/google/start/"
CALLBACK = "/api/v1/auth/google/callback/"

TURNSTILE_SECRET = "turnstile-test-secret-0c1d"
CLIENT_ID = "1234-test.apps.googleusercontent.com"
CLIENT_SECRET = "google-test-client-secret-77ab"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Recorder:
    """Stands in for requests.post; remembers every call."""

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[dict] = []

    def __call__(self, url, data=None, timeout=None, **kwargs):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(data) if callable(self.reply) else self.reply


# ---------------------------------------------------------------------------
# Turnstile
# ---------------------------------------------------------------------------


@pytest.fixture
def cloudflare(settings, monkeypatch):
    settings.TURNSTILE_SECRET_KEY = TURNSTILE_SECRET
    settings.TURNSTILE_ALLOWED_HOSTNAMES = []

    def install(reply):
        recorder = Recorder(reply)
        monkeypatch.setattr(turnstile_module.requests, "post", recorder)
        return recorder

    return install


def solved(action="login", hostname="www.getverifygh.com"):
    return FakeResponse({"success": True, "action": action, "hostname": hostname,
                         "error-codes": []})


def login(api, user, **extra):
    return api.post(LOGIN, {"email": user.email, "password": "Correct-Horse-Battery-1", **extra},
                    format="json")


def test_without_a_secret_there_is_no_check(api, user, monkeypatch):
    monkeypatch.setattr(turnstile_module.requests, "post", Recorder(AssertionError("called")))
    assert login(api, user).status_code == 200


def test_a_confirmed_token_signs_in_and_cloudflare_is_asked_properly(api, user, cloudflare):
    recorder = cloudflare(solved())
    response = login(api, user, turnstile_token="token-from-the-widget")
    assert response.status_code == 200, response.data
    (call,) = recorder.calls
    assert call["url"] == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert call["data"]["secret"] == TURNSTILE_SECRET
    assert call["data"]["response"] == "token-from-the-widget"
    assert call["timeout"]


def test_no_token_is_refused_before_cloudflare_or_the_password(api, user, cloudflare):
    recorder = cloudflare(solved())
    response = login(api, user)
    assert response.status_code == 400
    assert response.data["error"]["code"] == "HUMAN_CHECK_FAILED"
    assert recorder.calls == []
    # Not a failed password: a bot cannot lock the owner out from here.
    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert not LoginAttempt.objects.filter(email=user.email).exists()


def test_a_token_cloudflare_rejects_is_refused(api, user, cloudflare):
    cloudflare(FakeResponse({"success": False, "error-codes": ["invalid-input-response"]}))
    response = login(api, user, turnstile_token="forged")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "HUMAN_CHECK_FAILED"
    assert "vgh_access" not in response.cookies


def test_a_token_solved_for_another_form_is_refused(api, user, cloudflare):
    cloudflare(solved(action="register"))
    assert login(api, user, turnstile_token="t").status_code == 400


def test_a_token_from_another_hostname_is_refused(api, user, cloudflare, settings):
    cloudflare(solved(hostname="evil.example"))
    settings.TURNSTILE_ALLOWED_HOSTNAMES = ["www.getverifygh.com", "getverifygh.com"]
    assert login(api, user, turnstile_token="t").status_code == 400


def test_cloudflare_unreachable_fails_closed(api, user, cloudflare):
    cloudflare(requests.ConnectionError("down"))
    response = login(api, user, turnstile_token="t")
    assert response.status_code == 503
    assert response.data["error"]["code"] == "HUMAN_CHECK_UNAVAILABLE"
    assert "vgh_access" not in response.cookies


def test_registration_needs_the_check_too(api, cloudflare, django_capture_on_commit_callbacks):
    body = {"email": "abena@example.com", "password": "Correct-Horse-Battery-9",
            "accepted_terms": True}
    cloudflare(solved(action="register"))
    assert api.post(REGISTER, body, format="json").status_code == 400
    assert not User.objects.filter(email="abena@example.com").exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(REGISTER, {**body, "turnstile_token": "t"}, format="json")
    assert response.status_code == 201, response.data


def test_the_secret_and_token_are_never_logged(api, user, cloudflare, caplog):
    cloudflare(FakeResponse({"success": False, "error-codes": ["timeout-or-duplicate"]}))
    with caplog.at_level(logging.DEBUG):
        login(api, user, turnstile_token="token-that-must-not-be-logged")
    text = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    assert TURNSTILE_SECRET not in text
    assert "token-that-must-not-be-logged" not in text


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@pytest.fixture
def google_on(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = CLIENT_SECRET
    settings.GOOGLE_OAUTH_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback/"


def id_token(**claims) -> str:
    def part(value) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


def google_claims(expected_nonce, **overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-subject-1001",
        "email": "efua@gmail.com",
        "email_verified": True,
        "name": "Efua Boateng",
        "nonce": expected_nonce,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


def start(api, **params):
    response = api.get(START, params)
    assert response.status_code == 302
    pending = signing.loads(api.cookies["vgh_google"].value, salt="verifygh.google-sign-in")
    return response, pending


def finish(api, monkeypatch, pending, *, claims=None, token_reply=None, state=None, **query):
    """Come back from Google with a code; Google's token endpoint is faked."""
    if token_reply is None:
        token_reply = FakeResponse(
            {"id_token": id_token(**(claims or google_claims(pending["nonce"])))}
        )
    recorder = Recorder(token_reply)
    monkeypatch.setattr(google_module.requests, "post", recorder)
    params = {"state": pending["state"] if state is None else state, "code": "code-1", **query}
    return api.get(CALLBACK, params), recorder


def lands_on(response, path_and_query: str):
    assert response.status_code == 302, response.status_code
    expected = django_settings.VERIFYGH["FRONTEND_URL"].rstrip("/") + path_and_query
    assert response["Location"] == expected, response["Location"]


def test_the_google_button_is_offered_only_when_configured(api, settings):
    assert api.get(OPTIONS).json() == {"google": False}
    settings.GOOGLE_OAUTH_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = CLIENT_SECRET
    assert api.get(OPTIONS).json() == {"google": True}
    assert CLIENT_SECRET not in api.get(OPTIONS).content.decode()


def test_without_a_client_the_start_sends_them_back(api):
    lands_on(api.get(START), "/login?google=unavailable")


def test_start_sends_the_browser_to_google_with_pkce_and_state(api, google_on):
    response, pending = start(api, next="/orders")
    location = urlparse(response["Location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["state"] == [pending["state"]]
    assert query["nonce"] == [pending["nonce"]]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] and query["code_challenge"][0] != pending["verifier"]
    assert CLIENT_SECRET not in response["Location"]

    cookie = api.cookies["vgh_google"]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == CALLBACK
    assert pending["next"] == "/orders"


def test_a_new_google_account_is_created_verified_and_signed_in(api, google_on, monkeypatch):
    _, pending = start(api)
    response, recorder = finish(api, monkeypatch, pending)

    lands_on(response, "/dashboard")
    user = User.objects.get(email="efua@gmail.com")
    assert user.is_email_verified and user.email_verified_at
    assert user.google_subject == "google-subject-1001"
    assert user.full_name == "Efua Boateng"
    assert not user.has_usable_password()
    # Signed in on the sign-in page, where no terms were shown: the app asks.
    assert not user.has_accepted_current_terms
    assert response.cookies["vgh_access"].value
    assert response.cookies["vgh_refresh"]["httponly"]
    assert response.cookies["vgh_google"].value == ""  # the pending cookie is spent

    (call,) = recorder.calls
    assert call["url"] == "https://oauth2.googleapis.com/token"
    assert call["data"]["code_verifier"] == pending["verifier"]
    assert call["data"]["client_secret"] == CLIENT_SECRET

    me = api.get("/api/v1/auth/me/").json()["user"]
    assert me["email"] == "efua@gmail.com" and me["has_password"] is False


def test_sign_up_with_google_records_the_terms_and_the_invite(api, google_on, monkeypatch):
    _, pending = start(api, intent="signup", terms="1", ref="ABC123")
    assert pending["terms"] is True and pending["ref"] == "ABC123"
    response, _ = finish(api, monkeypatch, pending)
    lands_on(response, "/dashboard")
    assert User.objects.get(email="efua@gmail.com").has_accepted_current_terms


def test_terms_are_not_taken_from_the_sign_in_page(api, google_on):
    _, pending = start(api, terms="1")
    assert pending["terms"] is False


def test_an_existing_verified_account_is_linked_and_keeps_its_password(
    api, google_on, monkeypatch, user
):
    _, pending = start(api)
    claims = google_claims(pending["nonce"], email=user.email.upper())
    response, _ = finish(api, monkeypatch, pending, claims=claims)
    lands_on(response, "/dashboard")
    user.refresh_from_db()
    assert user.google_subject == "google-subject-1001"
    assert user.check_password("Correct-Horse-Battery-1")
    assert User.objects.filter(email__iexact=user.email).count() == 1


def test_linking_an_unverified_account_retires_a_password_nobody_proved(
    api, google_on, monkeypatch
):
    squatter = User.objects.create_user(email="efua@gmail.com", password="Squatter-Pass-123")
    version = squatter.token_version
    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending)
    lands_on(response, "/dashboard")
    squatter.refresh_from_db()
    assert squatter.is_email_verified
    assert not squatter.has_usable_password()
    assert squatter.token_version > version  # their sessions ended too


def test_an_address_linked_to_another_google_account_is_refused(api, google_on, monkeypatch, user):
    user.google_subject = "someone-else"
    user.save(update_fields=["google_subject"])
    _, pending = start(api)
    claims = google_claims(pending["nonce"], email=user.email)
    response, _ = finish(api, monkeypatch, pending, claims=claims)
    lands_on(response, "/login?google=conflict")
    assert "vgh_access" not in response.cookies


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"aud": "someone-elses-client"}, "failed"),
        ({"iss": "https://evil.example"}, "failed"),
        ({"nonce": "replayed-nonce"}, "failed"),
        ({"exp": int(time.time()) - 3600}, "failed"),
        ({"email_verified": False}, "unverified"),
        ({"sub": ""}, "failed"),
    ],
)
def test_an_id_token_that_fails_a_check_signs_no_one_in(
    api, google_on, monkeypatch, override, reason
):
    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending, claims=google_claims(pending["nonce"],
                                                                         **override))
    lands_on(response, f"/login?google={reason}")
    assert "vgh_access" not in response.cookies
    assert not User.objects.filter(email="efua@gmail.com").exists()


def test_a_callback_with_the_wrong_state_is_refused(api, google_on, monkeypatch):
    _, pending = start(api)
    response, recorder = finish(api, monkeypatch, pending, state="attacker-state")
    lands_on(response, "/login?google=expired")
    assert recorder.calls == []  # the code was never exchanged


def test_a_callback_without_the_pending_cookie_is_refused(api, google_on, monkeypatch):
    _, pending = start(api)
    api.cookies.pop("vgh_google")
    response, recorder = finish(api, monkeypatch, pending)
    lands_on(response, "/login?google=expired")
    assert recorder.calls == []


def test_cancelling_at_google_returns_to_the_form(api, google_on, monkeypatch):
    _, pending = start(api, intent="signup")
    response = api.get(CALLBACK, {"state": pending["state"], "error": "access_denied"})
    lands_on(response, "/register?google=cancelled")


def test_a_code_google_will_not_exchange_signs_no_one_in(api, google_on, monkeypatch):
    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending,
                         token_reply=FakeResponse({"error": "invalid_grant"}, 400))
    lands_on(response, "/login?google=failed")


def test_google_unreachable_is_reported_as_such(api, google_on, monkeypatch):
    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending,
                         token_reply=requests.ConnectionError("down"))
    lands_on(response, "/login?google=unavailable")


def test_a_suspended_account_is_not_signed_in(api, google_on, monkeypatch, user):
    user.is_suspended = True
    user.save(update_fields=["is_suspended"])
    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending,
                         claims=google_claims(pending["nonce"], email=user.email))
    lands_on(response, "/login?google=suspended")
    assert "vgh_access" not in response.cookies


def test_staff_land_in_the_console(api, google_on, monkeypatch, admin_user):
    _, pending = start(api, next="/orders")
    response, _ = finish(api, monkeypatch, pending,
                         claims=google_claims(pending["nonce"], email=admin_user.email))
    assert admin_user.role == Role.SUPER_ADMIN
    lands_on(response, "/admin")


@pytest.mark.parametrize("unsafe", ["//evil.example/x", "https://evil.example", "/\\evil.example",
                                    "orders", "/ok\r\nSet-Cookie: x=1"])
def test_next_never_leaves_the_site(api, google_on, unsafe):
    _, pending = start(api, next=unsafe)
    assert pending["next"] == "/dashboard"


def test_google_codes_and_secrets_are_never_logged(api, google_on, monkeypatch, caplog):
    _, pending = start(api)
    with caplog.at_level(logging.DEBUG):
        finish(api, monkeypatch, pending,
               token_reply=FakeResponse({"error": "invalid_grant"}, 400))
    text = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    for secret in (CLIENT_SECRET, "code-1", pending["verifier"], pending["nonce"]):
        assert secret not in text
