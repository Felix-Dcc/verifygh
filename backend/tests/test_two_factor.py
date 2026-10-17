"""Two-factor sign-in (apps/accounts/two_factor.py), required for staff.

Open since the September audit (O-4): a SUPER_ADMIN can adjust any balance, so
a stolen password alone must not be enough.
"""

from __future__ import annotations

import pytest
from django.conf import settings as django_settings

from apps.accounts import two_factor
from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
ADMIN_PASSWORD = "Correct-Horse-Battery-3"
LOGIN = "/api/v1/auth/login/"
VERIFY = "/api/v1/auth/2fa/verify/"
ME = "/api/v1/auth/me/"


def code_now(user, offset: int = 0) -> str:
    user.refresh_from_db()
    return two_factor.code_at(user.totp_secret, two_factor.current_step() + offset)


def enrol(user) -> list[str]:
    two_factor.begin_enrolment(user)
    return two_factor.enable(user)


def password_step(api, user, password=PASSWORD):
    return api.post(LOGIN, {"email": user.email, "password": password}, format="json")


@pytest.fixture
def required(settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "STAFF_TWO_FACTOR_REQUIRED": True}


# ---------------------------------------------------------------------------
# The algorithm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("unix_time", "expected"), [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
    (1234567890, "005924"), (2000000000, "279037"),
])
def test_codes_match_the_rfc_6238_test_vectors(unix_time, expected):
    """RFC 6238 appendix B (SHA-1), last six digits."""
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"
    step = two_factor.current_step(unix_time)
    assert two_factor.code_at(secret, step) == expected
    assert two_factor.matching_step(secret, expected, now=unix_time) == step


def test_a_code_from_far_outside_the_window_is_refused():
    secret = two_factor.new_secret()
    old = two_factor.code_at(secret, two_factor.current_step() - 5)
    assert two_factor.matching_step(secret, old) is None


# ---------------------------------------------------------------------------
# Turning it on
# ---------------------------------------------------------------------------


def test_setting_it_up_confirms_a_code_and_returns_recovery_codes_once(user, auth):
    client = auth(user)
    setup = client.post("/api/v1/auth/2fa/setup/", {}, format="json").data
    assert setup["otpauth_uri"].startswith("otpauth://totp/VerifyGH:")
    assert f"secret={setup['secret']}" in setup["otpauth_uri"]
    assert not User.objects.get(pk=user.pk).is_two_factor_enabled  # not until confirmed

    wrong = client.post("/api/v1/auth/2fa/enable/", {"code": "000000"}, format="json")
    assert wrong.status_code == 401
    response = client.post("/api/v1/auth/2fa/enable/", {"code": code_now(user)}, format="json")

    assert response.status_code == 200
    codes = response.data["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    user.refresh_from_db()
    assert user.is_two_factor_enabled
    # Stored only as keyed hashes.
    assert not set(codes) & set(user.two_factor_recovery_codes)
    me = client.get(ME).data["user"]
    assert me["is_two_factor_enabled"] and me["two_factor_recovery_codes_left"] == 10


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def test_a_password_alone_does_not_sign_in(api, user):
    enrol(user)
    response = password_step(api, user)

    assert response.status_code == 200
    assert response.data["two_factor_required"] is True
    assert "user" not in response.data
    assert django_settings.AUTH_COOKIE_ACCESS not in response.cookies
    assert response.cookies[two_factor.CHALLENGE_COOKIE]["httponly"]
    assert api.get(ME).status_code == 401


def test_the_code_finishes_signing_in(api, user):
    enrol(user)
    challenge = password_step(api, user).data["challenge"]

    response = api.post(VERIFY, {"challenge": challenge, "code": code_now(user)}, format="json")

    assert response.status_code == 200
    assert response.data["user"]["email"] == user.email
    assert response.cookies[django_settings.AUTH_COOKIE_ACCESS].value
    api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    assert api.get(ME).status_code == 200


def test_the_challenge_can_come_from_its_cookie(api, user):
    enrol(user)
    password_step(api, user)

    response = api.post(VERIFY, {"code": code_now(user)}, format="json")

    assert response.status_code == 200


def test_a_code_works_once(api, user):
    enrol(user)
    code = code_now(user)
    first = password_step(api, user).data["challenge"]
    assert api.post(VERIFY, {"challenge": first, "code": code}, format="json").status_code == 200

    second = password_step(api, user).data["challenge"]
    replay = api.post(VERIFY, {"challenge": second, "code": code}, format="json")

    assert replay.status_code == 401
    assert replay.data["error"]["code"] == "TWO_FACTOR_INVALID"


def test_a_challenge_gives_one_session(api, user):
    enrol(user)
    challenge = password_step(api, user).data["challenge"]
    api.post(VERIFY, {"challenge": challenge, "code": code_now(user)}, format="json")

    again = api.post(VERIFY, {"challenge": challenge, "code": code_now(user, 1)}, format="json")

    assert again.status_code == 401
    assert again.data["error"]["code"] == "TWO_FACTOR_EXPIRED"


def test_wrong_codes_lock_the_account_like_wrong_passwords(api, user, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_FAILED_LOGINS": 3}
    enrol(user)
    challenge = password_step(api, user).data["challenge"]
    for _ in range(3):
        assert api.post(VERIFY, {"challenge": challenge, "code": "123456"},
                        format="json").status_code == 401

    locked = api.post(VERIFY, {"challenge": challenge, "code": code_now(user)}, format="json")

    assert locked.status_code == 423
    assert User.objects.get(pk=user.pk).is_locked_out


def test_a_recovery_code_signs_in_once(api, user):
    codes = enrol(user)
    first = password_step(api, user).data["challenge"]
    assert api.post(VERIFY, {"challenge": first, "code": codes[0].lower()},
                    format="json").status_code == 200

    second = password_step(api, user).data["challenge"]
    assert api.post(VERIFY, {"challenge": second, "code": codes[0]},
                    format="json").status_code == 401
    assert len(User.objects.get(pk=user.pk).two_factor_recovery_codes) == 9


def test_a_password_change_voids_a_pending_challenge(api, user):
    enrol(user)
    challenge = password_step(api, user).data["challenge"]
    user.refresh_from_db()
    user.revoke_all_sessions()

    response = api.post(VERIFY, {"challenge": challenge, "code": code_now(user)}, format="json")

    assert response.status_code == 401
    assert response.data["error"]["code"] == "TWO_FACTOR_EXPIRED"


def test_a_stale_challenge_is_refused(api, user, monkeypatch):
    enrol(user)
    challenge = password_step(api, user).data["challenge"]
    monkeypatch.setattr(two_factor, "CHALLENGE_SECONDS", -1)

    response = api.post(VERIFY, {"challenge": challenge, "code": code_now(user)}, format="json")

    assert response.data["error"]["code"] == "TWO_FACTOR_EXPIRED"


def test_a_forged_challenge_is_refused(api, user):
    enrol(user)
    forged = f"{user.pk}:forged"
    response = api.post(VERIFY, {"challenge": forged, "code": code_now(user)}, format="json")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Google sign-in takes the same second step
# ---------------------------------------------------------------------------


def test_google_sign_in_also_asks_for_the_code(api, monkeypatch, settings):
    from test_turnstile_and_google import CLIENT_ID, CLIENT_SECRET, finish, start

    settings.GOOGLE_OAUTH_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = CLIENT_SECRET
    settings.GOOGLE_OAUTH_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback/"
    staff = User.objects.create_user(email="efua@gmail.com", password=PASSWORD,
                                     role=Role.ADMIN, is_email_verified=True,
                                     google_subject="google-subject-1001")
    enrol(staff)

    _, pending = start(api)
    response, _ = finish(api, monkeypatch, pending)

    assert response.status_code == 302
    assert "/login?two_factor=1&next=/admin" in response["Location"]
    assert django_settings.AUTH_COOKIE_ACCESS not in response.cookies
    assert api.post(VERIFY, {"code": code_now(staff)}, format="json").status_code == 200


# ---------------------------------------------------------------------------
# Required for staff
# ---------------------------------------------------------------------------


def test_staff_without_two_factor_cannot_use_the_admin_console(admin_user, auth, required):
    client = auth(admin_user, ADMIN_PASSWORD)

    response = client.get("/api/v1/admin/overview/")

    assert response.status_code == 403
    assert response.data["error"]["code"] == "TWO_FACTOR_SETUP_REQUIRED"
    assert client.get("/api/v1/admin/referrals-analytics/").status_code == 403
    me = client.get(ME).data["user"]
    assert me["two_factor_required"] is True and me["is_two_factor_enabled"] is False


def test_staff_with_two_factor_can(api, admin_user, required):
    enrol(admin_user)
    challenge = password_step(api, admin_user, ADMIN_PASSWORD).data["challenge"]
    signed_in = api.post(VERIFY, {"challenge": challenge, "code": code_now(admin_user)},
                         format="json")
    api.credentials(HTTP_X_CSRF_TOKEN=signed_in.data["csrf_token"])

    assert api.get("/api/v1/admin/overview/").status_code == 200


def test_customers_are_not_required_to(user, auth, required, catalog):
    client = auth(user)

    assert client.get(ME).data["user"]["two_factor_required"] is False
    assert client.get("/api/v1/wallet/").status_code == 200


def test_the_requirement_ships_on():
    """Production reads the base settings value, which defaults to on.

    In a fresh process with the variable unset: other tests swap the settings
    modules in and out of sys.modules, so nothing here may reload them.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if k != "STAFF_TWO_FACTOR_REQUIRED"}
    result = subprocess.run(
        [sys.executable, "-c", "from config.settings import base; "
                               "print(base.VERIFYGH['STAFF_TWO_FACTOR_REQUIRED'])"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True,
        timeout=60)
    assert result.stdout.strip() == "True", result.stderr[-500:]


# ---------------------------------------------------------------------------
# Turning it off, new recovery codes, and a reset by a super admin
# ---------------------------------------------------------------------------


def test_turning_it_off_needs_the_password_and_a_code(user, auth):
    client = auth(user)
    enrol(user)
    url = "/api/v1/auth/2fa/disable/"

    assert client.post(url, {"password": "wrong", "code": code_now(user)},
                       format="json").status_code == 400
    assert client.post(url, {"password": PASSWORD, "code": "000000"},
                       format="json").status_code == 401
    assert client.post(url, {"password": PASSWORD, "code": code_now(user)},
                       format="json").status_code == 200
    assert not User.objects.get(pk=user.pk).is_two_factor_enabled


def test_new_recovery_codes_replace_the_old_ones(user, auth):
    client = auth(user)
    old = enrol(user)

    response = client.post("/api/v1/auth/2fa/recovery-codes/",
                           {"password": PASSWORD, "code": code_now(user)}, format="json")

    assert response.status_code == 200
    assert not two_factor.use_recovery_code(User.objects.get(pk=user.pk), old[1])
    assert two_factor.use_recovery_code(User.objects.get(pk=user.pk),
                                        response.data["recovery_codes"][0])


def test_a_super_admin_can_reset_a_lost_device_with_a_reason(admin_user, auth, db):
    staff = User.objects.create_user(email="ops@verifygh.local", password=PASSWORD,
                                     role=Role.ADMIN, is_email_verified=True)
    enrol(staff)
    version = staff.token_version
    client = auth(admin_user, ADMIN_PASSWORD)
    url = f"/api/v1/admin/users/{staff.pk}/reset-two-factor/"

    assert client.post(url, {"reason": ""}, format="json").status_code == 400
    response = client.post(url, {"reason": "Lost phone, identity checked by call"},
                           format="json")

    assert response.status_code == 200
    staff.refresh_from_db()
    assert not staff.is_two_factor_enabled and not staff.totp_secret
    assert staff.token_version > version  # every session ended
    assert AdminAction.objects.filter(action="USER_TWO_FACTOR_RESET", admin=admin_user).exists()
    assert client.post(f"/api/v1/admin/users/{admin_user.pk}/reset-two-factor/",
                       {"reason": "Resetting myself"}, format="json").status_code == 400


def test_only_super_admins_can_reset(db, auth, user):
    admin = User.objects.create_user(email="plain-admin@verifygh.local", password=PASSWORD,
                                     role=Role.ADMIN, is_email_verified=True)
    enrol(user)
    response = auth(admin).post(f"/api/v1/admin/users/{user.pk}/reset-two-factor/",
                                {"reason": "Trying it on"}, format="json")

    assert response.status_code == 403
    assert User.objects.get(pk=user.pk).is_two_factor_enabled
