"""Authentication, session transport and account security."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core import mail

from apps.accounts.models import LoginAttempt, SecurityToken, TokenPurpose, User

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"

GOOD_PASSWORD = "Correct-Horse-Battery-1"


#: Registration queues the verification email with transaction.on_commit, which
#: never fires inside pytest-django's wrapping transaction. Capture and run it.
_capture_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture_on_commit
    _capture_on_commit = django_capture_on_commit_callbacks
    yield
    _capture_on_commit = None


def register(api, **overrides):
    body = {
        "email": "nana@example.com",
        "password": GOOD_PASSWORD,
        "full_name": "Nana Adjei",
        "accepted_terms": True,
    }
    body.update(overrides)
    with _capture_on_commit(execute=True):
        response = api.post(REGISTER, body, format="json")
    return response


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registration_creates_a_user_a_wallet_and_sends_verification(api):
    response = register(api)

    assert response.status_code == 201, response.data
    account = User.objects.get(email="nana@example.com")
    assert account.wallet.balance == 0
    assert account.is_email_verified is False
    assert account.accepted_terms_version == settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    assert len(mail.outbox) == 1
    assert "Confirm your email" in mail.outbox[0].subject


def test_password_is_hashed_not_stored(api):
    register(api)
    account = User.objects.get(email="nana@example.com")

    assert GOOD_PASSWORD not in account.password
    assert account.check_password(GOOD_PASSWORD)


def test_registration_requires_accepting_the_terms(api):
    response = register(api, accepted_terms=False)
    assert response.status_code == 400
    assert not User.objects.filter(email="nana@example.com").exists()


def test_weak_passwords_are_rejected(api):
    for weak in ("password123", "12345678901", "short"):
        response = register(api, password=weak)
        assert response.status_code == 400, weak


def test_ghanaian_phone_is_normalised_to_e164(api):
    register(api, phone="024 123 4599")
    assert User.objects.get(email="nana@example.com").phone == "+233241234599"


def test_duplicate_phone_is_rejected(api, user):
    response = register(api, phone="0241234567")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_sets_httponly_cookies_and_returns_a_csrf_token(api, user):
    response = api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")

    assert response.status_code == 200
    access = response.cookies[settings.AUTH_COOKIE_ACCESS]
    refresh = response.cookies[settings.AUTH_COOKIE_REFRESH]
    csrf = response.cookies[settings.AUTH_COOKIE_CSRF]

    # The tokens must be unreadable by script; the CSRF token must be readable.
    assert access["httponly"] is True
    assert refresh["httponly"] is True
    assert csrf["httponly"] == ""
    assert response.data["csrf_token"]

    # The token itself is never echoed into the response body.
    assert "access" not in response.data


def test_wrong_password_is_indistinguishable_from_unknown_email(api, user):
    wrong_password = api.post(
        LOGIN, {"email": user.email, "password": "Definitely-Not-It-9"}, format="json"
    )
    unknown_email = api.post(
        LOGIN, {"email": "ghost@example.com", "password": GOOD_PASSWORD}, format="json"
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.data["error"]["code"] == unknown_email.data["error"]["code"]
    assert wrong_password.data["error"]["message"] == unknown_email.data["error"]["message"]


def test_failed_logins_are_recorded(api, user):
    api.post(LOGIN, {"email": user.email, "password": "nope-nope-nope"}, format="json")
    attempt = LoginAttempt.objects.get(email=user.email)
    assert attempt.successful is False
    assert attempt.failure_reason == "bad_credentials"


def test_account_locks_after_repeated_failures(api, user, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_FAILED_LOGINS": 3}

    for _ in range(3):
        api.post(LOGIN, {"email": user.email, "password": "wrong-wrong-wrong"}, format="json")

    response = api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")
    assert response.status_code == 423
    assert response.data["error"]["code"] == "ACCOUNT_LOCKED"


def test_suspended_user_cannot_sign_in(api, user):
    user.is_suspended = True
    user.save(update_fields=["is_suspended"])

    response = api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "ACCOUNT_SUSPENDED"


# ---------------------------------------------------------------------------
# CSRF on the cookie transport
# ---------------------------------------------------------------------------


def test_unsafe_request_without_the_csrf_header_is_rejected(api, user):
    """Cookies alone must not authorise a write - that is the whole point."""
    api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")
    # Cookies are set on the client, but no X-CSRF-Token header is sent.

    response = api.patch("/api/v1/auth/me/", {"full_name": "Changed"}, format="json")

    assert response.status_code == 401
    user.refresh_from_db()
    assert user.full_name == "Kwame Mensah"


def test_wrong_csrf_token_is_rejected(api, user):
    api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")
    api.credentials(HTTP_X_CSRF_TOKEN="not-the-right-token")

    response = api.patch("/api/v1/auth/me/", {"full_name": "Changed"}, format="json")
    assert response.status_code == 401


def test_reads_do_not_need_the_csrf_header(api, user):
    api.post(LOGIN, {"email": user.email, "password": GOOD_PASSWORD}, format="json")
    assert api.get("/api/v1/auth/me/").status_code == 200


def test_correct_csrf_token_allows_the_write(api, user, auth):
    client = auth(user)
    response = client.patch("/api/v1/auth/me/", {"full_name": "Kwame A. Mensah"}, format="json")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.full_name == "Kwame A. Mensah"


def test_logout_clears_the_cookies(api, user, auth):
    client = auth(user)
    response = client.post("/api/v1/auth/logout/", {}, format="json")

    assert response.status_code == 200
    assert response.cookies[settings.AUTH_COOKIE_ACCESS].value == ""
    assert response.cookies[settings.AUTH_COOKIE_REFRESH].value == ""


# ---------------------------------------------------------------------------
# Email verification and password reset
# ---------------------------------------------------------------------------


def test_email_verification_round_trip(api, monkeypatch):
    captured = {}
    original = SecurityToken.issue

    def spy(cls_user, purpose, ttl_hours, ip=None):
        token, raw = original(cls_user, purpose, ttl_hours, ip)
        captured["raw"] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))

    register(api)
    response = api.post(
        "/api/v1/auth/email/verify/confirm/", {"token": captured["raw"]}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["is_email_verified"] is True


def test_verification_token_is_single_use(api, monkeypatch):
    captured = {}
    original = SecurityToken.issue

    def spy(cls_user, purpose, ttl_hours, ip=None):
        token, raw = original(cls_user, purpose, ttl_hours, ip)
        captured["raw"] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))
    register(api)

    url = "/api/v1/auth/email/verify/confirm/"
    assert api.post(url, {"token": captured["raw"]}, format="json").status_code == 200
    assert api.post(url, {"token": captured["raw"]}, format="json").status_code == 400


def test_only_the_token_hash_is_stored(api):
    register(api)
    account = User.objects.get(email="nana@example.com")
    token = SecurityToken.objects.get(user=account, purpose=TokenPurpose.EMAIL_VERIFICATION)

    assert len(token.token_hash) == 64
    assert not hasattr(token, "token")


def test_password_reset_does_not_reveal_whether_an_account_exists(api, user):
    known = api.post("/api/v1/auth/password/reset/", {"email": user.email}, format="json")
    unknown = api.post(
        "/api/v1/auth/password/reset/", {"email": "ghost@example.com"}, format="json"
    )

    assert known.status_code == unknown.status_code == 200
    assert known.data == unknown.data


def test_password_reset_changes_the_password(api, user, monkeypatch):
    captured = {}
    original = SecurityToken.issue

    def spy(cls_user, purpose, ttl_hours, ip=None):
        token, raw = original(cls_user, purpose, ttl_hours, ip)
        captured["raw"] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))

    api.post("/api/v1/auth/password/reset/", {"email": user.email}, format="json")
    response = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": captured["raw"], "new_password": "Brand-New-Passphrase-7"},
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password("Brand-New-Passphrase-7")

    assert api.post(
        LOGIN, {"email": user.email, "password": "Brand-New-Passphrase-7"}, format="json"
    ).status_code == 200


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


def test_accepting_terms_records_the_current_version(api, user, auth):
    user.accepted_terms_version = "old-version"
    user.save(update_fields=["accepted_terms_version"])
    client = auth(user)

    response = client.post("/api/v1/auth/terms/accept/", {"accepted": True}, format="json")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.accepted_terms_version == settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    assert user.accepted_terms_at is not None
