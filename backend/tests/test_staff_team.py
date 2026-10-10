"""The staff team: super admins invite admins and manage their roles.

What has to hold, whatever the UI does:

* only a super admin can change a role or invite staff;
* staff come in only by invitation: a customer account is never promoted -
  except former staff, as recorded in the admin log, who may be re-added;
* nobody changes their own role, and the last super admin stays one;
* a staff role goes only to an active, verified account;
* a demotion signs the person out everywhere at once;
* an invited admin chooses their own password from a one-time link - no one
  else ever sets it - and arrives verified, without Django-admin access;
* every change is audited with a reason, and no link is ever logged.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts import staff
from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.common.errors import Conflict

pytestmark = pytest.mark.django_db

SUPER_PASSWORD = "Correct-Horse-Battery-3"
STAFF_PASSWORD = "Correct-Horse-Battery-7"
INVITE_URL = "/api/v1/admin/users/invite/"
RESET_CONFIRM = "/api/v1/auth/password/reset/confirm/"


_on_commit = None


@pytest.fixture(autouse=True)
def _commit_hooks(django_capture_on_commit_callbacks):
    global _on_commit
    _on_commit = django_capture_on_commit_callbacks
    yield
    _on_commit = None


def sign_in(user: User, password: str) -> APIClient:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": user.email, "password": password},
                           format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def boss(admin_user):
    return sign_in(admin_user, SUPER_PASSWORD)


@pytest.fixture
def an_admin(db):
    return User.objects.create_user(email="ops@verifygh.local", password=STAFF_PASSWORD,
                                    role=Role.ADMIN, is_email_verified=True)


def set_role(client, target, role, reason="Joining the support rota"):
    with _on_commit(execute=True):
        return client.post(f"/api/v1/admin/users/{target.pk}/role/",
                           {"role": role, "reason": reason}, format="json")


def invite(client, email="esi@example.com", role=Role.ADMIN, reason="New operations lead"):
    return client.post(INVITE_URL, {"email": email, "full_name": "Esi Boateng", "role": role,
                                    "reason": reason}, format="json")


def link_token(message) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", message.body).group(1)


# ---------------------------------------------------------------------------
# Assigning roles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.ADMIN, Role.SUPER_ADMIN])
def test_a_customer_account_is_never_made_staff(boss, user, role):
    """Staff are created by invitation only."""
    response = set_role(boss, user, role)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "PROMOTION_DISABLED"
    user.refresh_from_db()
    assert user.role == Role.USER
    assert not AdminAction.objects.filter(action="USER_ROLE_CHANGE").exists()
    assert mail.outbox == []
    client = sign_in(user, "Correct-Horse-Battery-1")
    assert client.get("/api/v1/admin/overview/").status_code == 403


def test_a_former_staff_member_can_be_re_added(boss, admin_user, an_admin):
    assert set_role(boss, an_admin, Role.USER, reason="Left the company").status_code == 200
    listed = boss.get("/api/v1/admin/users/?former_staff=true").data["results"]
    assert [row["email"] for row in listed] == [an_admin.email]
    assert listed[0]["former_staff"] is True

    response = set_role(boss, an_admin, Role.SUPPORT, reason="Came back part-time")

    assert response.status_code == 200, response.data
    an_admin.refresh_from_db()
    assert an_admin.role == Role.SUPPORT
    entry = AdminAction.objects.filter(action="USER_ROLE_CHANGE").order_by("-created_at").first()
    assert entry.before == {"role": "USER"} and entry.after == {"role": "SUPPORT"}
    assert "Support" in mail.outbox[-1].subject
    client = sign_in(an_admin, STAFF_PASSWORD)
    assert client.get("/api/v1/admin/users/").status_code == 200


def test_a_customer_is_not_former_staff(boss, user):
    row = boss.get(f"/api/v1/admin/users/{user.pk}/").data
    assert row["former_staff"] is False
    assert boss.get("/api/v1/admin/users/?former_staff=true").data["results"] == []


def test_former_staff_is_read_from_the_admin_log_only(boss, user):
    """A staff role the log never recorded does not count."""
    User.objects.filter(pk=user.pk).update(role=Role.ADMIN)
    User.objects.filter(pk=user.pk).update(role=Role.USER)

    assert set_role(boss, user, Role.ADMIN).data["error"]["code"] == "PROMOTION_DISABLED"


def test_re_adding_someone_who_never_accepted_sends_a_fresh_invite(boss, api):
    invite(boss)
    invited = User.objects.get(email="esi@example.com")
    first = link_token(mail.outbox[0])
    assert set_role(boss, invited, Role.USER, reason="Hired someone else").status_code == 200

    response = set_role(boss, invited, Role.ADMIN, reason="Position reopened")

    assert response.status_code == 200, response.data
    assert response.data["invite_pending"] is True
    assert mail.outbox[-1].subject == "You're invited to the VerifyGH team"
    fresh = link_token(mail.outbox[-1])
    assert fresh != first
    accepted = api.post(RESET_CONFIRM, {"token": fresh, "new_password": STAFF_PASSWORD},
                        format="json")
    assert accepted.status_code == 200


def test_a_super_admin_can_move_staff_between_roles(boss, admin_user, support_user):
    response = set_role(boss, support_user, Role.ADMIN, reason="Promoted to operations")

    assert response.status_code == 200, response.data
    assert response.data["role"] == Role.ADMIN
    support_user.refresh_from_db()
    assert support_user.role == Role.ADMIN
    assert support_user.is_staff is False  # the Django admin stays closed

    entry = AdminAction.objects.get(action="USER_ROLE_CHANGE")
    assert entry.admin_id == admin_user.pk
    assert entry.before == {"role": "SUPPORT"} and entry.after == {"role": "ADMIN"}
    assert entry.reason == "Promoted to operations"
    assert [m.to for m in mail.outbox] == [[support_user.email]]
    assert "Admin" in mail.outbox[0].subject


@pytest.mark.parametrize("role", [Role.ADMIN, Role.SUPPORT])
def test_only_a_super_admin_can_assign_roles(role, user, db):
    actor = User.objects.create_user(email="lead@verifygh.local", password=STAFF_PASSWORD,
                                     role=role, is_email_verified=True)
    client = sign_in(actor, STAFF_PASSWORD)

    assert set_role(client, user, Role.SUPPORT).status_code == 403
    assert set_role(client, actor, Role.SUPER_ADMIN).status_code == 403
    user.refresh_from_db()
    actor.refresh_from_db()
    assert user.role == Role.USER and actor.role == role
    assert not AdminAction.objects.filter(action="USER_ROLE_CHANGE").exists()


def test_a_customer_cannot_reach_role_changes(user, other_user):
    client = sign_in(user, "Correct-Horse-Battery-1")
    assert set_role(client, other_user, Role.ADMIN).status_code == 403
    assert invite(client).status_code == 403


def test_nobody_changes_their_own_role(boss, admin_user):
    response = set_role(boss, admin_user, Role.ADMIN)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "OWN_ROLE"
    admin_user.refresh_from_db()
    assert admin_user.role == Role.SUPER_ADMIN


def test_a_role_change_needs_a_reason(boss, an_admin):
    response = set_role(boss, an_admin, Role.SUPPORT, reason="")
    assert response.status_code == 400
    an_admin.refresh_from_db()
    assert an_admin.role == Role.ADMIN


def test_an_unknown_role_is_refused(boss, user):
    assert set_role(boss, user, "OWNER").status_code == 400


def test_an_unverified_staff_account_cannot_be_moved_up(boss, db):
    unverified = User.objects.create_user(email="new@example.com", password=STAFF_PASSWORD,
                                          role=Role.SUPPORT)

    response = set_role(boss, unverified, Role.ADMIN)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMAIL_NOT_VERIFIED"
    unverified.refresh_from_db()
    assert unverified.role == Role.SUPPORT


def test_a_suspended_staff_account_keeps_only_the_way_out(boss, an_admin):
    an_admin.is_suspended = True
    an_admin.save(update_fields=["is_suspended"])

    response = set_role(boss, an_admin, Role.SUPPORT)
    assert response.status_code == 409
    assert response.data["error"]["code"] == "ACCOUNT_NOT_ACTIVE"
    # Removing access is always allowed.
    assert set_role(boss, an_admin, Role.USER, reason="Suspended for abuse").status_code == 200


def test_setting_the_same_role_is_reported(boss, an_admin):
    response = set_role(boss, an_admin, Role.ADMIN)
    assert response.status_code == 409
    assert response.data["error"]["code"] == "ROLE_UNCHANGED"


def test_a_demotion_signs_the_person_out_everywhere(boss, an_admin):
    their_session = sign_in(an_admin, STAFF_PASSWORD)
    assert their_session.get("/api/v1/admin/overview/").status_code == 200

    response = set_role(boss, an_admin, Role.USER, reason="Left the company")

    assert response.status_code == 200
    # Not when the access token expires: now.
    assert their_session.get("/api/v1/admin/overview/").status_code == 401
    assert "removed" in mail.outbox[-1].subject


def test_a_promotion_keeps_the_person_signed_in(boss, support_user):
    their_session = sign_in(support_user, "Correct-Horse-Battery-4")
    set_role(boss, support_user, Role.ADMIN)

    assert their_session.get("/api/v1/admin/users/").status_code == 200


def test_a_super_admin_can_appoint_and_demote_another_super_admin(boss, an_admin):
    assert set_role(boss, an_admin, Role.SUPER_ADMIN).status_code == 200
    assert set_role(boss, an_admin, Role.ADMIN, reason="Back to day-to-day ops").status_code == 200
    an_admin.refresh_from_db()
    assert an_admin.role == Role.ADMIN


def test_the_last_super_admin_cannot_be_demoted(admin_user, an_admin):
    """However the request arrives, someone must still hold the keys."""
    # A second super admin acting, but no longer active: only admin_user counts.
    acting = User.objects.create_user(email="old@verifygh.local", password=STAFF_PASSWORD,
                                      role=Role.SUPER_ADMIN, is_email_verified=True,
                                      is_suspended=True)

    with pytest.raises(Conflict) as caught:
        staff.change_role(target=admin_user, role=Role.ADMIN, reason="Testing the guard",
                          actor=acting)

    assert caught.value.code == "LAST_SUPER_ADMIN"
    admin_user.refresh_from_db()
    assert admin_user.role == Role.SUPER_ADMIN


def test_the_staff_filter_lists_only_the_team(boss, admin_user, an_admin, user):
    response = boss.get("/api/v1/admin/users/?staff=true")

    emails = {row["email"] for row in response.data["results"]}
    assert emails == {admin_user.email, an_admin.email}


# ---------------------------------------------------------------------------
# Inviting staff
# ---------------------------------------------------------------------------


def test_inviting_creates_a_staff_account_without_a_password(boss, admin_user):
    response = invite(boss)

    assert response.status_code == 201, response.data
    assert response.data["role"] == Role.ADMIN
    assert response.data["invite_pending"] is True
    assert response.data["invite_sent"] is True

    invited = User.objects.get(email="esi@example.com")
    assert invited.full_name == "Esi Boateng"
    assert not invited.has_usable_password()
    assert invited.is_staff is False and invited.is_superuser is False
    assert invited.is_email_verified is False

    entry = AdminAction.objects.get(action="STAFF_INVITED")
    assert entry.admin_id == admin_user.pk and entry.reason == "New operations lead"

    [message] = mail.outbox
    assert message.to == ["esi@example.com"]
    assert message.subject == "You're invited to the VerifyGH team"
    assert "/reset-password?token=" in message.body
    assert "invite=1" in message.body


def test_the_invitee_chooses_a_password_and_arrives_verified(boss, api):
    invite(boss)
    token = link_token(mail.outbox[0])

    response = api.post(RESET_CONFIRM, {"token": token, "new_password": STAFF_PASSWORD},
                        format="json")
    assert response.status_code == 200, response.data

    invited = User.objects.get(email="esi@example.com")
    assert invited.is_email_verified is True
    assert invited.has_usable_password()
    assert staff.invite_pending(invited) is False

    client = sign_in(invited, STAFF_PASSWORD)
    assert client.get("/api/v1/admin/overview/").status_code == 200
    # The link is single-use.
    again = api.post(RESET_CONFIRM, {"token": token, "new_password": "Another-Horse-9"},
                     format="json")
    assert again.status_code == 400


def test_an_invited_account_cannot_sign_in_before_choosing_a_password(boss, api):
    invite(boss)
    response = api.post("/api/v1/auth/login/", {"email": "esi@example.com", "password": ""},
                        format="json")
    assert response.status_code in (400, 401)


def test_inviting_an_existing_customer_email_is_refused(boss, user):
    response = invite(boss, email=user.email.upper())

    assert response.status_code == 409
    assert response.data["error"]["code"] == "EMAIL_TAKEN"
    assert mail.outbox == []


def test_an_invite_must_be_for_a_staff_role(boss):
    assert invite(boss, role=Role.USER).status_code == 400
    assert not User.objects.filter(email="esi@example.com").exists()


def test_only_a_super_admin_can_invite(an_admin):
    client = sign_in(an_admin, STAFF_PASSWORD)

    assert invite(client).status_code == 403
    assert not User.objects.filter(email="esi@example.com").exists()


def test_resending_an_invite_retires_the_earlier_link(boss, api):
    invite(boss)
    first = link_token(mail.outbox[0])
    invited = User.objects.get(email="esi@example.com")

    response = boss.post(f"/api/v1/admin/users/{invited.pk}/resend-invite/")
    assert response.status_code == 200
    second = link_token(mail.outbox[1])
    assert first != second

    stale = api.post(RESET_CONFIRM, {"token": first, "new_password": STAFF_PASSWORD},
                     format="json")
    assert stale.status_code == 400
    fresh = api.post(RESET_CONFIRM, {"token": second, "new_password": STAFF_PASSWORD},
                     format="json")
    assert fresh.status_code == 200


def test_an_accepted_invite_cannot_be_resent(boss, an_admin):
    response = boss.post(f"/api/v1/admin/users/{an_admin.pk}/resend-invite/")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "INVITE_ACCEPTED"


def test_an_admin_cannot_resend_invites(boss, an_admin):
    invite(boss)
    invited = User.objects.get(email="esi@example.com")
    client = sign_in(an_admin, STAFF_PASSWORD)

    assert client.post(f"/api/v1/admin/users/{invited.pk}/resend-invite/").status_code == 403


def test_invite_links_are_never_logged(boss, caplog):
    caplog.set_level(logging.DEBUG)
    invite(boss)
    token = link_token(mail.outbox[0])

    assert token not in caplog.text
    assert not any(token in str(getattr(r, "__dict__", "")) for r in caplog.records)


def test_a_password_reset_also_verifies_the_address(api, db):
    """Opening a link from the inbox proves the inbox, whichever link it was."""
    account = User.objects.create_user(email="forgot@example.com", password=STAFF_PASSWORD)
    api.post("/api/v1/auth/password/reset/", {"email": account.email}, format="json")
    token = link_token(mail.outbox[-1])

    response = api.post(RESET_CONFIRM, {"token": token, "new_password": "Brand-New-Horse-5"},
                        format="json")

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.is_email_verified is True


# ---------------------------------------------------------------------------
# Dashboard charts
# ---------------------------------------------------------------------------


def test_chart_series_cover_every_day_even_quiet_ones(boss, catalog):
    response = boss.get("/api/v1/admin/charts/?days=14")

    assert response.status_code == 200
    series = response.data["series"]
    assert len(series) == 14
    dates = [row["date"] for row in series]
    assert dates == sorted(dates) and len(set(dates)) == 14
    for key in ("revenue", "cost", "profit", "orders", "completed", "refunded", "failed",
                "active", "deposits", "deposit_count", "signups", "verified_signups"):
        assert key in series[0]
    assert set(response.data["totals"]) == set(response.data["previous_totals"])


def test_chart_totals_count_revenue_profit_and_outcomes(boss, user, catalog):
    from django.utils import timezone

    from apps.catalog.models import Country, Provider, Service
    from apps.orders.models import Order, OrderStatus

    def order(ref, status, price, cost="0.50"):
        return Order.objects.create(
            reference=ref, user=user, service=Service.objects.get(slug="instagram"),
            country=Country.objects.get(code="US"), provider=Provider.objects.first(),
            price=Decimal(price), provider_cost=Decimal(cost), exchange_rate=Decimal("12.00"),
            idempotency_key=ref, status=status,
        )

    order("VGH-CHART1", OrderStatus.COMPLETED, "15.00")
    order("VGH-CHART2", OrderStatus.CODE_RECEIVED, "10.00")
    order("VGH-CHART3", OrderStatus.REFUNDED, "15.00")
    order("VGH-CHART4", OrderStatus.EXPIRED, "15.00")

    data = boss.get("/api/v1/admin/charts/?days=7").data
    today = data["series"][-1]

    assert today["date"] == str(timezone.localdate())
    assert today["orders"] == 4
    assert (today["completed"], today["refunded"], today["failed"]) == (2, 1, 1)
    assert Decimal(today["revenue"]) == Decimal("25.00")
    assert Decimal(today["cost"]) == Decimal("12.00")  # 2 x $0.50 x 12.00
    assert Decimal(today["profit"]) == Decimal("13.00")
    totals = data["totals"]
    assert Decimal(totals["revenue"]) == Decimal("25.00")
    assert totals["success_rate"] == 50.0
    assert data["previous_totals"]["orders"] == 0
    assert data["previous_totals"]["success_rate"] is None
