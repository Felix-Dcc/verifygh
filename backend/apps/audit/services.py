"""Audit and abuse-signal helpers.

`record_audit` is intentionally forgiving: an audit write must never be the
reason a user's action fails. It logs loudly on failure instead.
`record_admin_action` is the opposite - if it cannot be written, the privileged
operation must not proceed, so it raises.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.audit.models import AdminAction, AuditLog, SuspicionLevel, SuspiciousActivity
from apps.common.logging import redact_mapping
from apps.common.middleware import get_client_ip

logger = logging.getLogger("verifygh.audit")

SHARED_DEVICE_THRESHOLD = 3


def _target_bits(target) -> tuple[str, str]:
    if target is None:
        return "", ""
    return target.__class__.__name__, str(getattr(target, "pk", ""))


def record_audit(*, actor=None, action: str, target=None, request=None, metadata=None) -> None:
    target_type, target_id = _target_bits(target)
    try:
        AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            actor_email=getattr(actor, "email", "") or "",
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=(get_client_ip(request) if request else None) or None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
            request_id=getattr(request, "request_id", "") if request else "",
            metadata=redact_mapping(metadata or {}),
        )
    except Exception:
        logger.exception("audit_write_failed", extra={"action": action})


def _json_safe(value):
    """As stored in a JSON column: UUIDs, Decimals and datetimes as strings.

    Serializer output carries UUID foreign keys (a pricing rule's service and
    country), which the JSON column cannot store as they are - every edit of a
    service-scoped pricing rule failed on 10 Oct 2026, rolling the edit back.
    """
    import json

    from django.core.serializers.json import DjangoJSONEncoder

    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def record_admin_action(*, admin, action: str, target, reason: str, before=None, after=None,
                        request=None) -> AdminAction:
    """Write the privileged-action record. Raises if it cannot be written."""
    if not reason or not reason.strip():
        raise ValueError("An admin action requires a reason.")
    target_type, target_id = _target_bits(target)
    entry = AdminAction.objects.create(
        admin=admin,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason.strip(),
        before=_json_safe(redact_mapping(before or {})),
        after=_json_safe(redact_mapping(after or {})),
        ip_address=(get_client_ip(request) if request else None) or None,
        request_id=getattr(request, "request_id", "") if request else "",
    )
    record_audit(
        actor=admin, action=f"ADMIN_{action}", target=target, request=request,
        metadata={"reason": reason[:500], "admin_action_id": str(entry.id)},
    )
    return entry


def flag(*, user, kind: str, level: str = SuspicionLevel.LOW, description: str = "",
         evidence=None, dedupe_hours: int = 24) -> SuspiciousActivity | None:
    """Raise an abuse signal, collapsing repeats within `dedupe_hours`."""
    from datetime import timedelta

    if dedupe_hours:
        recent = SuspiciousActivity.objects.filter(
            user=user,
            kind=kind,
            resolved=False,
            created_at__gte=timezone.now() - timedelta(hours=dedupe_hours),
        ).first()
        if recent:
            return recent
    try:
        entry = SuspiciousActivity.objects.create(
            user=user,
            kind=kind,
            level=level,
            description=description,
            evidence=redact_mapping(evidence or {}),
        )
    except Exception:
        logger.exception("suspicious_activity_write_failed", extra={"kind": kind})
        return None

    logger.warning(
        "suspicious_activity", extra={"kind": kind, "level": level,
                                      "user_id": str(getattr(user, "id", "-"))}
    )
    _bump_risk_score(user, level)
    return entry


def _bump_risk_score(user, level: str) -> None:
    if user is None:
        return
    increment = {"LOW": 1, "MEDIUM": 5, "HIGH": 15}.get(str(level), 1)
    type(user).objects.filter(pk=user.pk).update(
        risk_score=min(user.risk_score + increment, 1000)
    )


def evaluate_device_sharing(*, user, fingerprint_hash: str, ip: str | None = None) -> None:
    """Flag when one device drives several accounts.

    This is not proof of abuse - a shared family phone or an internet cafe looks
    identical - so it is recorded as a LOW/MEDIUM signal for human review only.
    """
    from apps.accounts.models import UserDevice

    account_count = (
        UserDevice.objects.filter(fingerprint_hash=fingerprint_hash)
        .values("user_id")
        .distinct()
        .count()
    )
    if account_count < SHARED_DEVICE_THRESHOLD:
        return

    flag(
        user=user,
        kind=SuspiciousActivity.Kind.SHARED_DEVICE,
        level=SuspicionLevel.MEDIUM if account_count >= 5 else SuspicionLevel.LOW,
        description=f"This device has been seen on {account_count} accounts.",
        # The fingerprint is a salted hash, never the raw user agent and IP;
        # kept so a reviewer can see which accounts share this device.
        evidence={"account_count": account_count, "ip": ip or "",
                  "fingerprint_hash": fingerprint_hash},
        dedupe_hours=72,
    )


def resolve_flag(*, flag_id, admin, note: str) -> SuspiciousActivity:
    entry = SuspiciousActivity.objects.get(pk=flag_id)
    entry.resolved = True
    entry.resolved_at = timezone.now()
    entry.resolved_by = admin
    entry.resolution_note = note
    entry.save(update_fields=["resolved", "resolved_at", "resolved_by", "resolution_note",
                              "updated_at"])
    return entry
