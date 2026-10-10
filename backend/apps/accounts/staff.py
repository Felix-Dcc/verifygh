"""The staff team: super admins invite admins and manage their roles.

Only USER_ROLE_CHANGE (super admins) may act here, and the rules are about
never locking the business out and never handing out a session by accident:

* staff accounts are created only by invitation - a customer account is never
  turned into a staff one (10 Oct 2026, the owner's call). The one exception
  is former staff: someone whose access was removed may be re-added. "Former"
  is read from the immutable admin log, never from a flag anyone can set;
* nobody changes their own role;
* the last active super admin cannot be demoted;
* a staff role goes only to an active, unsuspended account whose email is
  verified - an unverified address may not even belong to the person;
* a demotion ends every session at once, so lost access is lost now;
* every change carries a reason, is recorded with record_admin_action, and is
  emailed to the person it concerns.

An invited admin gets an account with no usable password and a one-time link
to choose one (the password-reset flow, which also verifies the address).
Nobody else ever sets or sees a staff password.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.accounts.constants import STAFF_ROLES, Role
from apps.accounts.models import SecurityToken, TokenPurpose, User
from apps.common.errors import Conflict, ValidationFailed
from apps.common.middleware import get_client_ip

logger = logging.getLogger("verifygh.accounts.staff")

#: How long an invitation link stays valid.
STAFF_INVITE_TTL_HOURS = 72

ROLE_LABELS = {str(value): str(label) for value, label in Role.choices}


def _frontend(path: str) -> str:
    from apps.accounts.services import _frontend as frontend

    return frontend(path)


def _active_super_admins(exclude_pk=None) -> int:
    queryset = User.objects.filter(role=Role.SUPER_ADMIN, is_active=True, is_suspended=False)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.count()


def former_staff_actions():
    """Admin-log rows that prove an account once held staff access."""
    from django.db.models import Q

    from apps.audit.models import AdminAction

    return AdminAction.objects.filter(target_type=User.__name__).filter(
        Q(action="STAFF_INVITED")
        | Q(action="USER_ROLE_CHANGE", before__role__in=[str(r) for r in STAFF_ROLES])
    )


def was_staff(user: User) -> bool:
    return former_staff_actions().filter(target_id=str(user.pk)).exists()


def staff_history_ids() -> set[str]:
    """Every account id the admin log shows holding staff access. A small set."""
    return set(former_staff_actions().values_list("target_id", flat=True).distinct())


def _notify_role(user: User, role: str, actor: User) -> None:
    from apps.notifications.services import notify

    if role in STAFF_ROLES:
        title = f"You're now {ROLE_LABELS[role]} on VerifyGH"
        body = (f"{actor.full_name or actor.email} gave your account the {ROLE_LABELS[role]} "
                f"role. Sign in and open the admin console to get started.")
    else:
        title = "Your VerifyGH staff access was removed"
        body = ("Your account no longer has staff access. You can still use VerifyGH as a "
                "customer. Contact the team if you think this is a mistake.")
    notify(user, event="SECURITY_ALERT", title=title, body=body, channels=("EMAIL", "IN_APP"))


def change_role(*, target: User, role: str, reason: str, actor: User, request=None) -> User:
    """Give `target` a new role, under the rules above."""
    from apps.audit.services import record_admin_action

    role = str(role or "").upper()
    if role not in ROLE_LABELS:
        raise ValidationFailed("Choose a valid role.",
                               details={"fields": {"role": ["Choose a valid role."]}})
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason (at least 5 characters).",
                               details={"fields": {"reason": ["At least 5 characters."]}})
    if target.pk == actor.pk:
        raise Conflict("You can't change your own role.", code="OWN_ROLE")

    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=target.pk)
        previous = locked.role
        if previous == role:
            raise Conflict(f"This account is already {ROLE_LABELS[role]}.", code="ROLE_UNCHANGED")
        if previous == Role.USER and role in STAFF_ROLES and not was_staff(locked):
            raise Conflict("Customer accounts can't be given staff access. Invite new admins "
                           "from the Team page instead.", code="PROMOTION_DISABLED")
        # Removed before they ever accepted their invitation: re-adding them
        # sends a fresh invitation, which is what verifies the address.
        reinvite = (previous == Role.USER and role in STAFF_ROLES
                    and not locked.has_usable_password())
        if role in STAFF_ROLES:
            if not locked.is_active or locked.is_suspended:
                raise Conflict("A suspended or inactive account can't be given a staff role.",
                               code="ACCOUNT_NOT_ACTIVE")
            if not locked.is_email_verified and not reinvite:
                raise Conflict("Their email isn't verified yet. Staff roles go only to verified "
                               "accounts - ask them to finish setting up first.",
                               code="EMAIL_NOT_VERIFIED")
        if previous == Role.SUPER_ADMIN and _active_super_admins(exclude_pk=locked.pk) == 0:
            raise Conflict("This is the last super admin. Make someone else a super admin first.",
                           code="LAST_SUPER_ADMIN")

        locked.role = role
        locked.save(update_fields=["role", "updated_at"])
        record_admin_action(
            admin=actor, action="USER_ROLE_CHANGE", target=locked, reason=reason,
            before={"role": previous}, after={"role": role}, request=request,
        )
        demoted = _rank(role) < _rank(previous)
        if demoted:
            # Lost access has to be lost now, not when a token expires.
            locked.revoke_all_sessions()

    logger.info("user_role_changed", extra={"user_id": str(locked.pk), "from": previous,
                                            "to": role, "demoted": demoted})
    if reinvite:
        transaction.on_commit(lambda: send_invite(locked, actor=actor, request=request))
    else:
        transaction.on_commit(lambda: _notify_role(locked, role, actor))
    locked.refresh_from_db()
    return locked


def _rank(role: str) -> int:
    return {Role.USER: 0, Role.SUPPORT: 1, Role.ADMIN: 2, Role.SUPER_ADMIN: 3}.get(role, 0)


def invite_staff(*, email: str, full_name: str, role: str, reason: str, actor: User,
                 request=None) -> tuple[User, bool]:
    """Create a staff account and email its owner a link to choose a password.

    Returns (user, delivered). An undelivered invite leaves the account in
    place, pending, for "Resend invite".
    """
    from apps.audit.services import record_admin_action

    email = (email or "").strip().lower()
    role = str(role or "").upper()
    if role not in [str(r) for r in STAFF_ROLES]:
        raise ValidationFailed("Choose a staff role.",
                               details={"fields": {"role": ["Choose a staff role."]}})
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason (at least 5 characters).",
                               details={"fields": {"reason": ["At least 5 characters."]}})
    if User.objects.filter(email__iexact=email).exists():
        raise Conflict("An account already uses this email. Staff need an email that isn't "
                       "registered on VerifyGH.", code="EMAIL_TAKEN")

    with transaction.atomic():
        user = User.objects.create_user(email=email, password=None,
                                        full_name=(full_name or "").strip()[:150], role=role)
        record_admin_action(
            admin=actor, action="STAFF_INVITED", target=user, reason=reason,
            after={"email": email, "role": role}, request=request,
        )
    logger.info("staff_invited", extra={"user_id": str(user.pk), "role": role})
    return user, send_invite(user, actor=actor, request=request)


def invite_pending(user: User) -> bool:
    """An invited staff member who has not chosen a password yet."""
    return user.role in STAFF_ROLES and not user.has_usable_password()


def send_invite(user: User, *, actor: User, request=None) -> bool:
    """(Re)send the set-your-password link. True if the provider accepted it."""
    from apps.notifications.models import DeliveryStatus
    from apps.notifications.services import notify

    if not invite_pending(user):
        raise Conflict("This person has already set up their account.", code="INVITE_ACCEPTED")
    ip = get_client_ip(request) if request else None
    _token, raw = SecurityToken.issue(user, TokenPurpose.PASSWORD_RESET, STAFF_INVITE_TTL_HOURS, ip)
    sent = notify(
        user,
        event="SECURITY_ALERT",
        title="You're invited to the VerifyGH team",
        subject="You're invited to the VerifyGH team",
        body=f"{actor.full_name or actor.email} invited you to VerifyGH as "
             f"{ROLE_LABELS[user.role]}.",
        email_template="emails/staff_invite.txt",
        context={
            "full_name": user.full_name or "there",
            "inviter": actor.full_name or actor.email,
            "role": ROLE_LABELS[user.role],
            "setup_url": _frontend(f"/reset-password?token={raw}&invite=1"),
            "hours": STAFF_INVITE_TTL_HOURS,
        },
        channels=("EMAIL",),
    )
    delivered = any(n.delivery_status == DeliveryStatus.SENT for n in sent)
    logger.info("staff_invite_sent", extra={"user_id": str(user.pk), "delivered": delivered})
    return delivered
