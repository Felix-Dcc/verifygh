"""Sign-in, end to end, the way a customer actually goes through it.

Written for "I can register but not sign in, and resetting my password doesn't
help". The cause was that registration and password reset stripped surrounding
whitespace from the password while sign-in did not, so a password pasted with a
trailing space or newline was stored one way and checked another. The
whitespace tests below reproduce that report exactly; the rest pin down every
other step of the journey so a regression anywhere in it shows up here.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import LoginAttempt, SecurityToken, User
from apps.accounts.services import password_candidates

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"
LOGOUT = "/api/v1/auth/logout/"
REFRESH = "/api/v1/auth/refresh/"
ME = "/api/v1/auth/me/"
VERIFY = "/api/v1/auth/email/verify/confirm/"
RESET = "/api/v1/auth/password/reset/"
RESET_CONFIRM = "/api/v1/auth/password/reset/confirm/"
CHANGE = "/api/v1/auth/password/change/"

PASSWORD = "Correct-Horse-Battery-1"
NEW_PASSWORD = "Brand-New-Passphrase-7"


@pytest.fixture
def issued(monkeypatch):
    """The raw value of every security token issued, by purpose.

    Only the hash is stored, so a test has to catch the raw token on its way out
    - exactly as it would leave in the email.
    """
    tokens: dict[str, str] = {}
    original = SecurityToken.issue

    def spy(user, purpose, ttl_hours, ip=None, **options):
        token, raw = original(user, purpose, ttl_hours, ip, **options)
        tokens[str(purpose)] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))
    return tokens


@pytest.fixture
def journey(django_capture_on_commit_callbacks, issued):
    """Helpers that drive the public API only - no model shortcuts."""

    class Journey:
        def register(self, api, email="esi@example.com", password=PASSWORD):
            with django_capture_on_commit_callbacks(execute=True):
                return api.post(REGISTER, {
                    "email": email, "password": password,
                    "full_name": "Esi Boateng", "accepted_terms": True,
                }, format="json")

        def login(self, api, email="esi@example.com", password=PASSWORD):
            response = api.post(LOGIN, {"email": email, "password": password}, format="json")
            if response.status_code == 200:
                api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
            return response

        def verify_email(self, api):
            return api.post(VERIFY, {"token": issued["EMAIL_VERIFICATION"]}, format="json")

        def reset(self, api, new_password, email="esi@example.com"):
            with django_capture_on_commit_callbacks(execute=True):
                api.post(RESET, {"email": email}, format="json")
            return api.post(RESET_CONFIRM, {
                "token": issued["PASSWORD_RESET"], "new_password": new_password,
            }, format="json")

    return Journey()


def fresh() -> APIClient:
    return APIClient()


def code(response) -> str:
    return response.data["error"]["code"]


# ---------------------------------------------------------------------------
# The whole journey
# ---------------------------------------------------------------------------


def test_register_verify_logout_login_reset_and_login_again(journey):
    api = fresh()
    assert journey.register(api).status_code == 201

    # Straight after registering, the same password signs in.
    assert journey.login(api).status_code == 200
    # Verify the email; still signed in.
    assert journey.verify_email(api).status_code == 200
    assert api.get(ME).data["user"]["is_email_verified"] is True
    # Sign out, sign back in.
    assert api.post(LOGOUT, {}, format="json").status_code == 200
    api = fresh()
    assert journey.login(api).status_code == 200

    # Reset: the new password works and the old one does not.
    assert journey.reset(fresh(), NEW_PASSWORD).status_code == 200
    assert journey.login(fresh(), password=NEW_PASSWORD).status_code == 200
    old = journey.login(fresh(), password=PASSWORD)
    assert old.status_code == 401
    assert code(old) == "INVALID_CREDENTIALS"


def test_unverified_account_can_still_sign_in(journey):
    """Verification gates purchases, not sign-in - you need to be signed in to
    ask for a new verification email."""
    api = fresh()
    journey.register(api)
    response = journey.login(api)

    assert response.status_code == 200
    assert response.data["user"]["is_email_verified"] is False


# ---------------------------------------------------------------------------
# The reported bug: whitespace around the password
# ---------------------------------------------------------------------------

PADDINGS = [
    pytest.param("", " ", id="trailing-space"),
    pytest.param(" ", "", id="leading-space"),
    pytest.param("", "\n", id="trailing-newline"),
    pytest.param("\t", "  ", id="both-sides"),
]


@pytest.mark.parametrize("before,after", PADDINGS)
def test_a_padded_password_signs_in_after_registering_with_it(journey, before, after):
    typed = before + PASSWORD + after
    assert journey.register(fresh(), password=typed).status_code == 201

    assert journey.login(fresh(), password=typed).status_code == 200
    # And without the padding, which is what was actually stored.
    assert journey.login(fresh(), password=PASSWORD).status_code == 200


@pytest.mark.parametrize("before,after", PADDINGS)
def test_a_padded_password_signs_in_after_resetting_to_it(journey, before, after):
    """The second half of the report: resetting didn't help, because the reset
    stripped the new password exactly as registration had."""
    typed = before + NEW_PASSWORD + after
    journey.register(fresh())
    assert journey.reset(fresh(), typed).status_code == 200

    assert journey.login(fresh(), password=typed).status_code == 200
    assert journey.login(fresh(), password=NEW_PASSWORD).status_code == 200


def test_a_password_really_stored_with_whitespace_still_signs_in_exactly():
    """createsuperuser and the shell don't strip, so the exact string must keep
    working - it is tried first."""
    User.objects.create_user(email="ops@example.com", password=" spaced-secret-99 ")

    exact = fresh().post(LOGIN, {"email": "ops@example.com",
                                 "password": " spaced-secret-99 "}, format="json")
    assert exact.status_code == 200


def test_whitespace_is_not_a_wildcard(journey):
    journey.register(fresh())

    for wrong in ("   ", PASSWORD[:-1] + " ", PASSWORD + "x", PASSWORD.lower()):
        assert journey.login(fresh(), password=wrong).status_code in (400, 401), repr(wrong)


def test_a_failed_padded_attempt_counts_once_toward_the_lockout(journey, user):
    journey.login(fresh(), email=user.email, password="wrong-password-1 ")
    user.refresh_from_db()

    assert user.failed_login_count == 1
    assert LoginAttempt.objects.filter(user=user, successful=False).count() == 1


def test_password_candidates():
    assert password_candidates("abc") == ["abc"]
    assert password_candidates(" abc\n") == [" abc\n", "abc"]
    assert password_candidates("   ") == ["   "]


def test_change_password_accepts_the_current_password_as_typed(journey):
    api = fresh()
    journey.register(api, password=PASSWORD + " ")
    journey.login(api, password=PASSWORD + " ")

    response = api.post(CHANGE, {"current_password": PASSWORD + " ",
                                 "new_password": NEW_PASSWORD}, format="json")

    assert response.status_code == 200, response.data
    assert journey.login(fresh(), password=NEW_PASSWORD).status_code == 200


# ---------------------------------------------------------------------------
# Email address handling
# ---------------------------------------------------------------------------


def test_email_is_case_insensitive_and_trimmed(journey):
    journey.register(fresh(), email="Esi.Boateng@Example.com")

    assert User.objects.filter(email="esi.boateng@example.com").exists()
    for typed in ("esi.boateng@example.com", "ESI.BOATENG@EXAMPLE.COM",
                  "  Esi.Boateng@example.com  "):
        assert journey.login(fresh(), email=typed).status_code == 200, typed


def test_duplicate_registration_is_refused_whatever_the_case(journey):
    assert journey.register(fresh()).status_code == 201
    again = journey.register(fresh(), email="ESI@example.com", password=NEW_PASSWORD)

    assert again.status_code == 400
    assert User.objects.filter(email__iexact="esi@example.com").count() == 1
    # The original password is untouched.
    assert journey.login(fresh()).status_code == 200


# ---------------------------------------------------------------------------
# Refusals are distinguishable where they should be, and only there
# ---------------------------------------------------------------------------


def test_wrong_password_and_unknown_email_look_the_same(journey):
    journey.register(fresh())
    wrong = journey.login(fresh(), password="Not-The-Password-9")
    unknown = journey.login(fresh(), email="nobody@example.com")

    assert wrong.status_code == unknown.status_code == 401
    # Identical apart from the per-request id.
    for response in (wrong, unknown):
        response.data["error"].pop("request_id", None)
    assert wrong.data == unknown.data
    assert code(wrong) == "INVALID_CREDENTIALS"


def test_suspended_account_is_told_so(journey):
    journey.register(fresh())
    User.objects.filter(email="esi@example.com").update(is_suspended=True)
    response = journey.login(fresh())

    assert response.status_code == 403
    assert code(response) == "ACCOUNT_SUSPENDED"


def test_locked_account_is_told_so_and_reset_unlocks_it(journey, settings):
    # Below the per-minute throttle, so the lockout is what answers.
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_FAILED_LOGINS": 3}
    journey.register(fresh())
    for _ in range(3):
        journey.login(fresh(), password="Not-The-Password-9")

    locked = journey.login(fresh())
    assert locked.status_code == 423
    assert code(locked) == "ACCOUNT_LOCKED"

    assert journey.reset(fresh(), NEW_PASSWORD).status_code == 200
    assert journey.login(fresh(), password=NEW_PASSWORD).status_code == 200


def test_an_unusable_password_never_signs_in():
    account = User.objects.create_user(email="nopass@example.com", password=None)
    assert not account.has_usable_password()

    for guess in ("", " ", "!", account.password):
        response = fresh().post(LOGIN, {"email": "nopass@example.com", "password": guess},
                                format="json")
        assert response.status_code in (400, 401)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_login_issues_working_access_and_refresh_tokens(journey):
    api = fresh()
    journey.register(api)
    response = journey.login(api)

    access = response.cookies[settings.AUTH_COOKIE_ACCESS]
    refresh = response.cookies[settings.AUTH_COOKIE_REFRESH]
    assert access.value and access["httponly"]
    assert refresh.value and refresh["httponly"]
    assert "access" not in response.data and "refresh" not in response.data

    assert api.get(ME).status_code == 200
    assert api.post(REFRESH, {}, format="json").status_code == 200
    assert api.get(ME).status_code == 200


def test_signing_in_on_two_devices_keeps_both_sessions(journey):
    journey.register(fresh())
    phone, laptop = fresh(), fresh()

    assert journey.login(phone).status_code == 200
    assert journey.login(laptop).status_code == 200
    assert phone.get(ME).status_code == 200
    assert laptop.get(ME).status_code == 200

    # Signing out on one leaves the other alone.
    assert phone.post(LOGOUT, {}, format="json").status_code == 200
    assert laptop.get(ME).status_code == 200


def test_a_reset_signs_out_every_existing_session(journey):
    api = fresh()
    journey.register(api)
    journey.login(api)
    assert api.get(ME).status_code == 200

    journey.reset(fresh(), NEW_PASSWORD)

    assert api.get(ME).status_code == 401
    assert api.post(REFRESH, {}, format="json").status_code == 401


def test_a_reset_token_works_once(journey, issued):
    journey.register(fresh())
    assert journey.reset(fresh(), NEW_PASSWORD).status_code == 200

    replay = fresh().post(RESET_CONFIRM, {"token": issued["PASSWORD_RESET"],
                                          "new_password": "Third-Passphrase-44"},
                          format="json")

    assert replay.status_code == 400
    assert journey.login(fresh(), password=NEW_PASSWORD).status_code == 200
    assert journey.login(fresh(), password="Third-Passphrase-44").status_code == 401


def test_the_per_account_throttle_cannot_be_dodged_with_case_or_spaces(journey):
    journey.register(fresh())
    cache.clear()
    spellings = ["esi@example.com", "ESI@example.com", " esi@example.com", "esi@example.com "]
    answers = [
        journey.login(fresh(), email=spellings[i % 4], password="Not-The-Password-9").status_code
        for i in range(12)
    ]

    assert 429 in answers


def test_nothing_secret_reaches_the_login_attempt_log(journey):
    journey.register(fresh())
    journey.login(fresh(), password="Leaky-Guess-123 ")
    journey.login(fresh())

    for attempt in LoginAttempt.objects.all():
        row = " ".join(str(v) for v in attempt.__dict__.values())
        assert PASSWORD not in row and "Leaky-Guess-123" not in row
