"""Site-wide maintenance: the "Pause site" button in the admin.

Production, 6 Oct 2026: the number provider stopped handing out numbers and
every order was charged, failed twenty seconds later and was refunded. Staff
need one switch that stops customers up front instead.

Two levels. BUYING_PAUSED refuses new orders and number reuse. ALL_PAUSED also
refuses new top-ups - money in is only safe when it can be spent. Neither
touches anything already under way: an order waiting for its code is still
polled and refunded if none comes, a deposit the customer is approving on
their phone (OTP, PIN prompt, webhook) is still credited, refunds and the
expiry sweeps run, and sign-in, wallets and the admin keep working. Enforced
in the two service-layer checks every purchase and deposit already passes
(check_purchase_eligibility, deposits_blocked_reason) - never as middleware,
which could catch a webhook by accident.

Nothing reopens the site by itself: `expected_back_at` is only shown to
customers. Reopening while the provider is still broken would be 6 Oct again.

Read on every purchase and deposit attempt, so the answer is cached briefly
and refreshed the moment staff change it; a cache that cannot be read falls
back to the database.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.common.errors import ServiceUnavailable, ValidationFailed

logger = logging.getLogger("verifygh.maintenance")

CACHE_KEY = "maintenance-state:v1"
CACHE_SECONDS = 10

#: Why staff pause, as one tap on a phone. Stored in the audit log; never
#: shown to customers, who get the notice below.
PRESET_REASONS = (
    "Numbers unavailable from our supplier",
    "Payments delayed",
    "Planned update",
    "Investigating a problem",
)

BUYING_NOTICE = (
    "Buying numbers is paused for a short while. Your balance is safe and nothing "
    "will be charged. Open orders still finish or are refunded automatically."
)
ALL_NOTICE = BUYING_NOTICE + " Top-ups are paused too."
DEPOSITS_NOTICE = (
    "Top-ups are paused for a short while. Your balance is safe, and you can still buy "
    "numbers with it."
)

#: How far ahead "expected back" may be shown.
EXPECTED_BACK_MAX_MINUTES = 24 * 60
MESSAGE_MAX_LENGTH = 300


class SiteMaintenance(ServiceUnavailable):
    code = "MAINTENANCE"
    message = BUYING_NOTICE
    #: A refusal staff asked for: not logged as a server error.
    expected = True


def _modes():
    from apps.common.models import MaintenanceMode

    return MaintenanceMode


def _answer(state) -> dict:
    mode = _modes()
    current = state.mode if state is not None else mode.OFF
    paused = current != mode.OFF
    default = {mode.ALL_PAUSED: ALL_NOTICE,
               mode.DEPOSITS_PAUSED: DEPOSITS_NOTICE}.get(current, BUYING_NOTICE)
    return {
        "mode": str(current),
        "buying_open": current not in (mode.BUYING_PAUSED, mode.ALL_PAUSED),
        "deposits_open": current not in (mode.DEPOSITS_PAUSED, mode.ALL_PAUSED),
        "message": ((state.message or default) if paused else ""),
        "since": state.since.isoformat() if paused and state.since else None,
        "expected_back_at": (state.expected_back_at.isoformat()
                             if paused and state.expected_back_at else None),
    }


def current() -> dict:
    """What customers are told now: mode, whether buying and top-ups are open,
    the notice, and when it started and is expected to end."""
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:
        cached = None  # read the database instead
    if cached is not None:
        return cached
    from apps.common.models import MaintenanceState

    answer = _answer(MaintenanceState.objects.filter(pk=1).first())
    try:
        cache.set(CACHE_KEY, answer, CACHE_SECONDS)
    except Exception:
        pass
    return answer


def require_buying_open() -> None:
    """Refuse a purchase, before any money moves, while buying is paused."""
    state = current()
    if not state["buying_open"]:
        raise SiteMaintenance(state["message"] or BUYING_NOTICE)


def deposits_notice() -> str:
    """The notice while top-ups are paused, "" while they are open."""
    state = current()
    return "" if state["deposits_open"] else (state["message"] or ALL_NOTICE)


def report() -> dict:
    """The full state, for staff."""
    from apps.common.models import MaintenanceState

    state = MaintenanceState.objects.select_related("updated_by").filter(pk=1).first()
    return {
        **_answer(state),
        "reason": state.reason if state and state.mode != _modes().OFF else "",
        "custom_message": state.message if state else "",
        "updated_at": state.updated_at.isoformat() if state else None,
        "updated_by": (getattr(state.updated_by, "email", "") or "") if state else "",
        "preset_reasons": list(PRESET_REASONS),
        "notices": {"BUYING_PAUSED": BUYING_NOTICE, "DEPOSITS_PAUSED": DEPOSITS_NOTICE,
                    "ALL_PAUSED": ALL_NOTICE},
    }


def set_mode(*, mode, reason, actor, message="", expected_back_minutes=None,
             request=None) -> dict:
    """Pause, change the level, or reopen. Audited with who and why; staff are told."""
    from apps.accounts.constants import AdminPermission
    from apps.audit.services import record_admin_action
    from apps.common.models import MaintenanceState
    from apps.notifications.staff import alert_staff

    modes = _modes()
    if mode not in modes.values:
        raise ValidationFailed("Choose whether to pause buying, pause buying and top-ups, "
                               "or reopen.")
    reason = str(reason or "").strip()
    if len(reason) < 3:
        raise ValidationFailed("Say why - pick one of the reasons.")
    message = str(message or "").strip()
    if len(message) > MESSAGE_MAX_LENGTH:
        raise ValidationFailed(f"Keep the notice to {MESSAGE_MAX_LENGTH} characters.")
    back_at = None
    if expected_back_minutes not in (None, ""):
        try:
            minutes = int(expected_back_minutes)
        except (TypeError, ValueError):
            raise ValidationFailed("Choose when you expect to be back.") from None
        if not 0 < minutes <= EXPECTED_BACK_MAX_MINUTES:
            raise ValidationFailed("Choose when you expect to be back.")
        back_at = timezone.now() + timedelta(minutes=minutes)

    with transaction.atomic():
        MaintenanceState.objects.get_or_create(pk=1)
        state = MaintenanceState.objects.select_for_update().get(pk=1)
        before = {"mode": state.mode, "reason": state.reason, "message": state.message}
        was_open = state.mode == modes.OFF
        paused = mode != modes.OFF

        state.mode = mode
        state.updated_by = actor
        if paused:
            state.reason = reason[:300]
            state.message = message
            state.expected_back_at = back_at
            if was_open:
                state.since = timezone.now()
        else:
            state.since = None
            state.expected_back_at = None
        state.save()

        action = ("MAINTENANCE_OFF" if not paused
                  else "MAINTENANCE_ON" if was_open else "MAINTENANCE_CHANGED")
        record_admin_action(
            admin=actor, action=action, target=state, reason=reason[:500], before=before,
            after={"mode": state.mode, "reason": state.reason, "message": state.message},
            request=request,
        )
        answer = _answer(state)
        transaction.on_commit(lambda: _publish(answer))

        who = getattr(actor, "email", "") or "staff"
        if paused:
            title = {modes.ALL_PAUSED: "Site paused: buying and top-ups",
                     modes.DEPOSITS_PAUSED: "Site paused: top-ups"}.get(mode,
                                                                     "Site paused: buying")
            body = (f"{who} paused the site: {reason}. Customers see the maintenance notice "
                    "until someone reopens it in the admin.")
        else:
            title = "Site is live again"
            body = f"{who} reopened the site: {reason}."
        alert_staff(permission=AdminPermission.MAINTENANCE_MANAGE, event="STAFF_MAINTENANCE",
                    title=title, body=body, link="/admin/system", reference=action)

    logger.warning("site_maintenance_changed", extra={"mode": mode, "action": action})
    return report()


def _publish(answer: dict) -> None:
    try:
        cache.set(CACHE_KEY, answer, CACHE_SECONDS)
    except Exception:
        # Every process still picks it up from the database within CACHE_SECONDS.
        logger.warning("maintenance_cache_publish_failed")
