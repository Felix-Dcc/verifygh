"""Admin API keys (apps/accounts/api_keys.py, apps/adminapi/api_keys.py).

A key lets a program act as one staff member on the admin API when no browser
session is available. These tests pin down both halves: that it works for the
job it was made for, and every way it must stop working.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import api_keys, two_factor
from apps.accounts.constants import Role
from apps.accounts.models import AdminApiKey, ApiKeyAccess
from apps.audit.models import AdminAction, AuditLog, SuspiciousActivity

pytestmark = pytest.mark.django_db

KEYS = "/api/v1/admin/api-keys/"
FLAGS = "/api/v1/admin/flags/"


def code_now(user) -> str:
    user.refresh_from_db()
    return two_factor.code_at(user.totp_secret, two_factor.current_step())


def enrol(user):
    two_factor.begin_enrolment(user)
    two_factor.enable(user)
    user.refresh_from_db()


def with_key(raw: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def make_key(user, access=ApiKeyAccess.WRITE, days=30) -> tuple[AdminApiKey, str]:
    return api_keys.create_key(owner=user, name="Assistant", access=access, days=days)


@pytest.fixture
def flag(user):
    return SuspiciousActivity.objects.create(
        user=user, kind="SHARED_DEVICE", level="MEDIUM", description="Two accounts, one device",
    )


# ---------------------------------------------------------------------------
# Making a key
# ---------------------------------------------------------------------------


def test_creating_a_key_needs_two_factor_and_shows_the_key_once(admin_user, auth):
    client = auth(admin_user, "Correct-Horse-Battery-3")
    refused = client.post(KEYS, {"name": "Assistant", "access": "WRITE"}, format="json")
    assert refused.status_code == 400
    assert refused.data["error"]["code"] == "TWO_FACTOR_REQUIRED"

    enrol(admin_user)
    wrong = client.post(KEYS, {"name": "Assistant", "code": "000000"}, format="json")
    assert wrong.status_code == 400

    made = client.post(KEYS, {"name": "Assistant", "access": "WRITE", "days": 30,
                              "code": code_now(admin_user)}, format="json")
    assert made.status_code == 201, made.data
    raw = made.data["key"]
    assert raw.startswith("vgh_ak_")

    stored = AdminApiKey.objects.get(pk=made.data["id"])
    assert raw not in stored.key_hash and stored.prefix in raw  # only a hash is kept
    assert stored.expires_at - timezone.now() > timedelta(days=29)

    listed = client.get(KEYS).data
    assert [k["id"] for k in listed] == [made.data["id"]]
    assert "key" not in listed[0]
    assert AdminAction.objects.filter(action="API_KEY_CREATE").count() == 1


def test_expiry_is_limited_to_the_offered_choices(admin_user, auth):
    client = auth(admin_user, "Correct-Horse-Battery-3")
    enrol(admin_user)
    response = client.post(KEYS, {"name": "Forever", "days": 3650,
                                  "code": code_now(admin_user)}, format="json")
    assert response.status_code == 400


def test_at_most_five_live_keys(admin_user):
    for _ in range(api_keys.MAX_ACTIVE_PER_OWNER):
        make_key(admin_user)
    with pytest.raises(api_keys.TooManyKeys):
        make_key(admin_user)


def test_you_only_see_and_revoke_your_own_keys(admin_user, auth, db):
    from apps.accounts.models import User

    other = User.objects.create_user(email="ops@verifygh.local", password="Correct-Horse-9",
                                     role=Role.ADMIN, is_email_verified=True)
    theirs, _ = make_key(other)
    client = auth(admin_user, "Correct-Horse-Battery-3")
    assert client.get(KEYS).data == []
    assert client.post(f"{KEYS}{theirs.pk}/revoke/").status_code == 404


# ---------------------------------------------------------------------------
# Using a key
# ---------------------------------------------------------------------------


def test_a_key_resolves_an_abuse_signal_and_the_record_says_so(admin_user, flag):
    key, raw = make_key(admin_user)
    client = with_key(raw)

    listed = client.get(FLAGS)
    assert listed.status_code == 200
    assert [f["id"] for f in listed.data["results"]] == [str(flag.pk)]

    resolved = client.post(f"{FLAGS}{flag.pk}/resolve/",
                           {"note": "Same household, no abuse found"}, format="json")
    assert resolved.status_code == 200, resolved.data
    flag.refresh_from_db()
    assert flag.resolved and flag.resolved_by == admin_user

    entry = AuditLog.objects.get(action="ADMIN_FLAG_RESOLVE")
    assert entry.actor == admin_user
    assert entry.metadata["via_admin_key"]["id"] == str(key.pk)
    key.refresh_from_db()
    assert key.last_used_at is not None


def test_a_key_carries_its_owners_permissions_not_more(support_user, flag):
    _, raw = make_key(support_user)
    client = with_key(raw)
    assert client.get(FLAGS).status_code == 200
    # Resolving needs USER_SUSPEND, which support does not have.
    assert client.post(f"{FLAGS}{flag.pk}/resolve/", {"note": "fine"},
                       format="json").status_code == 403


def test_a_read_only_key_cannot_act(admin_user, flag):
    _, raw = make_key(admin_user, access=ApiKeyAccess.READ)
    client = with_key(raw)
    assert client.get(FLAGS).status_code == 200
    assert client.post(f"{FLAGS}{flag.pk}/resolve/", {"note": "fine"},
                       format="json").status_code == 403
    flag.refresh_from_db()
    assert not flag.resolved


def test_a_key_works_on_the_admin_api_only(admin_user):
    _, raw = make_key(admin_user)
    client = with_key(raw)
    assert client.get("/api/v1/auth/me/").status_code == 403
    assert client.get("/api/v1/wallet/").status_code == 403


def test_a_key_cannot_manage_keys(admin_user):
    enrol(admin_user)
    key, raw = make_key(admin_user)
    client = with_key(raw)
    assert client.get(KEYS).status_code == 403
    assert client.post(KEYS, {"name": "Longer", "days": 90,
                              "code": code_now(admin_user)}, format="json").status_code == 403
    assert client.post(f"{KEYS}{key.pk}/revoke/").status_code == 403


# ---------------------------------------------------------------------------
# When a key stops working
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["revoked", "expired", "signed_out", "suspended",
                                    "demoted", "deactivated"])
def test_a_key_stops_working(admin_user, change):
    key, raw = make_key(admin_user)
    if change == "revoked":
        api_keys.revoke_key(key, by=admin_user)
    elif change == "expired":
        AdminApiKey.objects.filter(pk=key.pk).update(expires_at=timezone.now())
    elif change == "signed_out":
        admin_user.revoke_all_sessions()
    elif change == "suspended":
        admin_user.is_suspended = True
        admin_user.save()
    elif change == "demoted":
        admin_user.role = Role.USER
        admin_user.save()
    elif change == "deactivated":
        admin_user.is_active = False
        admin_user.save()

    assert with_key(raw).get(FLAGS).status_code == 401


def test_a_wrong_secret_with_a_real_prefix_is_refused(admin_user):
    key, raw = make_key(admin_user)
    forged = raw[: raw.rindex("_") + 1] + "A" * 43
    assert with_key(forged).get(FLAGS).status_code == 401
    assert with_key("vgh_ak_nothing").get(FLAGS).status_code == 401


def test_revoking_from_the_console_is_recorded(admin_user, auth):
    key, raw = make_key(admin_user)
    client = auth(admin_user, "Correct-Horse-Battery-3")
    response = client.post(f"{KEYS}{key.pk}/revoke/")
    assert response.status_code == 200
    assert response.data["status"] == "REVOKED"
    assert AdminAction.objects.filter(action="API_KEY_REVOKE").count() == 1
    assert with_key(raw).get(FLAGS).status_code == 401


def test_a_key_never_reaches_the_logs_whole(admin_user):
    from apps.common.logging import redact_text

    _, raw = make_key(admin_user)
    cleaned = redact_text(f"calling with {raw} now")
    assert raw not in cleaned and raw[:16] in cleaned
