"""Number quality: history, the flagged-number screen, customer reports and
what staff do about them. See models.py for why the vocabulary is careful.

Money rules, restated because this module is the one place that refunds an
order whose code was delivered:

* A report never moves money by itself. Refunds and replacements are staff
  decisions, each written to the AdminAction log with a reason - with one
  exception: a report sent to a provider that refunds reported verifications
  (TextVerified) is refunded when, and only when, that provider refunds us for
  it. Until then staff can neither refund nor replace it; if the provider
  declines, the claim is rejected with the provider's reply.
* A refund goes through `orders.services.issue_refund`, so it gets the same
  ledger entry, the same one-refund-per-order constraint and the same audit as
  every other refund.
* A replacement costs the customer nothing and writes no ledger entry at all.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.audit.models import SuspicionLevel, SuspiciousActivity
from apps.audit.services import flag, record_admin_action, record_audit
from apps.common.errors import Conflict, ServiceUnavailable, ValidationFailed
from apps.common.ids import issue_reference, order_reference
from apps.common.middleware import get_client_ip
from apps.common.money import format_ghs
from apps.numbers.models import (
    EXCLUDED_QUALITIES,
    OPEN_ISSUE_STATUSES,
    IssueEvidence,
    IssueReason,
    IssueStatus,
    NumberQuality,
    NumberRecord,
    NumberUsage,
    ProviderReportStatus,
    UsageDisposition,
    VerificationIssue,
)

logger = logging.getLogger("verifygh.numbers")

#: Reasons the replacement/refund policy covers: the number itself could not be
#: used for the service. The others are real problems too, but a delivered code
#: that "didn't work" is as often the service as the number, so staff look at
#: them case by case rather than the report counting as qualifying.
POLICY_REASONS = frozenset({IssueReason.NUMBER_ALREADY_LINKED, IssueReason.SERVICE_REJECTED_NUMBER})

CUSTOMER_MESSAGE = (
    "Thanks for reporting this. We've flagged this number for review. If the number is "
    "confirmed unusable for the requested service, your order will be handled according "
    "to our replacement/refund policy."
)


# ---------------------------------------------------------------------------
# Identity of a number
# ---------------------------------------------------------------------------


def _digits(number: str) -> str:
    return "".join(ch for ch in str(number or "") if ch.isdigit())


def fingerprint(number: str) -> str:
    """A keyed hash of the number's digits.

    Keyed with the server's secret so the history table cannot be reversed by
    hashing every possible number. The cost: rotating SECRET_KEY starts the
    history afresh, because old fingerprints stop matching.
    """
    return salted_hmac("apps.numbers.fingerprint", _digits(number), algorithm="sha256").hexdigest()


def mask(number: str, dial_code: str = "") -> str:
    """+1 *** *** 4234 - enough for support to tell numbers apart, no more."""
    digits = _digits(number)
    if not digits:
        return ""
    dial = _digits(dial_code)
    if dial and digits.startswith(dial) and len(digits) > len(dial) + 4:
        return f"+{dial} *** *** {digits[-4:]}"
    return f"+{digits[:2]}*** {digits[-4:]}"


def _record(order, number: str) -> NumberRecord:
    record, _ = NumberRecord.objects.get_or_create(
        provider=order.provider,
        service=order.service,
        fingerprint=fingerprint(number),
        defaults={"number_masked": mask(number, order.country.dial_code)},
    )
    return record


def _set_quality(record: NumberRecord, quality: str) -> None:
    NumberRecord.objects.filter(pk=record.pk).update(
        quality=quality, quality_changed_at=timezone.now()
    )
    record.quality = quality


# ---------------------------------------------------------------------------
# History, and the screen on new purchases
# ---------------------------------------------------------------------------


def is_excluded(order, number: str) -> bool:
    """Whether this number is flagged for this order's service.

    A report is per service: a number flagged for TikTok is still sold for
    Telegram. Only BLOCKED - a problem with the number itself - reaches across
    services.
    """
    if not number:
        return False
    return NumberRecord.objects.filter(
        Q(service=order.service, quality__in=EXCLUDED_QUALITIES)
        | Q(quality=NumberQuality.BLOCKED),
        provider=order.provider,
        fingerprint=fingerprint(number),
    ).exists()


def note_assigned(order) -> NumberUsage | None:
    """Record that `order` was given its number. Safe to call more than once."""
    if not order.phone_number:
        return None
    existing = NumberUsage.objects.filter(
        order=order, disposition=UsageDisposition.ASSIGNED
    ).select_related("record").first()
    if existing is not None:
        return existing

    now = timezone.now()
    record = _record(order, order.phone_number)
    NumberRecord.objects.filter(pk=record.pk).update(
        times_issued=F("times_issued") + 1,
        last_issued_at=now,
        first_issued_at=record.first_issued_at or now,
    )
    return NumberUsage.objects.create(
        record=record,
        order=order,
        user=order.user,
        provider_order_id=order.provider_order_id,
        disposition=UsageDisposition.ASSIGNED,
        acquired_at=order.created_at if order.created_at else now,
        assigned_at=now,
    )


def turn_away(order, provider, result) -> NumberUsage:
    """Release a flagged number the provider just gave us, and remember doing so.

    Releasing is not always instant - OnlineSim refuses to close an operation
    with no SMS for 120 seconds (300 for WhatsApp) - so a refused release is
    retried later by a task rather than abandoned, which would leave our
    balance frozen and a concurrency slot held.
    """
    record = _record(order, result.phone_number)
    usage = NumberUsage.objects.create(
        record=record,
        order=order,
        user=order.user,
        provider_order_id=result.provider_order_id,
        disposition=UsageDisposition.EXCLUDED,
        acquired_at=timezone.now(),
    )
    logger.info(
        "number_turned_away",
        extra={"order": order.reference, "quality": record.quality},
    )
    released = False
    try:
        released = bool(provider.cancel_order(result.provider_order_id))
    except Exception:
        logger.warning("number_release_failed", extra={"order": order.reference})
    if released:
        NumberUsage.objects.filter(pk=usage.pk).update(released=True)
    else:
        from apps.numbers.tasks import release_turned_away_number

        release_turned_away_number.apply_async(
            args=[str(usage.pk)],
            countdown=provider.release_retry_after_seconds(
                order.provider_service_code or order.service.slug
            ),
        )
    return usage


# ---------------------------------------------------------------------------
# Customer reports
# ---------------------------------------------------------------------------


def _window_hours() -> int:
    return int(settings.VERIFYGH["NUMBER_ISSUE_REPORT_WINDOW_HOURS"])


def report_window(order) -> timedelta:
    """How long after the code arrives a problem can be reported.

    A provider that reviews reports (TextVerified) only refunds a report made
    within minutes of the code arriving - a claim filed six minutes after was
    declined for exactly that - and our refund follows theirs, so its window
    is ours. Other providers' orders keep the longer policy window.
    """
    if provider_reviews_reports(order.provider.adapter_key):
        return timedelta(
            minutes=int(settings.VERIFYGH["NUMBER_ISSUE_PROVIDER_REPORT_WINDOW_MINUTES"]))
    return timedelta(hours=_window_hours())


def describe_window(window: timedelta) -> str:
    minutes = int(window.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{minutes // 60} hours"


def report_window_ends(order):
    if not order.code_received_at:
        return None
    return order.code_received_at + report_window(order)


def can_report(order) -> bool:
    """Whether the order screen should offer "Report a problem"."""
    if getattr(order, "issue", None) is not None:
        return False
    ends = report_window_ends(order)
    return bool(
        order.phone_number and ends and timezone.now() <= ends
        and order.refund_status != "COMPLETED"
    )


def issue_for(order) -> VerificationIssue | None:
    try:
        return order.issue
    except VerificationIssue.DoesNotExist:
        return None


def _qualification(order, reason: str) -> list[dict]:
    ends = report_window_ends(order)
    return [
        {"check": "A verification code was delivered to this number",
         "ok": bool(order.code_received_at)},
        {"check": f"Reported within {describe_window(report_window(order))} of the code "
                  "arriving",
         "ok": bool(ends and timezone.now() <= ends)},
        {"check": "The reason is covered by the replacement/refund policy",
         "ok": reason in POLICY_REASONS},
        {"check": "The order has not already been refunded",
         "ok": order.refund_status != "COMPLETED"},
    ]


def _risk_flags(order, user, ip: str | None) -> list[dict]:
    """Patterns worth a person's attention. Never a verdict.

    Several reports in a month can be bad luck with a recycled pool as easily as
    abuse, so nothing here refuses a report or lowers its standing - it only
    decides whether staff see a "look closer" marker.
    """
    from apps.orders.models import Order

    now = timezone.now()
    flags: list[dict] = []
    threshold = int(settings.VERIFYGH["NUMBER_ISSUE_REVIEW_THRESHOLD"])

    recent = VerificationIssue.objects.filter(user=user, created_at__gte=now - timedelta(days=30))
    reports = recent.count() + 1  # including this one
    if reports >= threshold:
        flags.append({"code": "FREQUENT_REPORTER",
                      "detail": f"{reports} reports in the last 30 days."})

    remedied = recent.filter(status__in=[IssueStatus.REFUNDED, IssueStatus.REPLACED]).count()
    if remedied >= 2:
        flags.append({"code": "REPEAT_REMEDIES",
                      "detail": f"{remedied} refunds or replacements from reports in 30 days."})

    delivered = Order.objects.filter(
        user=user, code_received_at__isnull=False, created_at__gte=now - timedelta(days=90)
    ).count()
    if delivered >= 4 and reports / delivered >= 0.5:
        flags.append({"code": "HIGH_REPORT_RATIO",
                      "detail": f"{reports} reports against {delivered} delivered orders in 90 days."})

    if ip:
        shared = (
            VerificationIssue.objects.filter(ip_address=ip, created_at__gte=now - timedelta(days=7))
            .exclude(user=user).values("user").distinct().count()
        )
        if shared:
            flags.append({"code": "SHARED_IP",
                          "detail": f"{shared} other account(s) reported from this address this week."})

    if user.created_at and now - user.created_at < timedelta(days=1):
        flags.append({"code": "NEW_ACCOUNT", "detail": "Account is less than a day old."})

    if order.code_received_at and now - order.code_received_at > timedelta(hours=24):
        flags.append({"code": "LATE_REPORT",
                      "detail": "Reported more than 24 hours after the code arrived."})
    return flags


def report_issue(order, *, user, reason: str, details: str = "",
                 confirmed_existing_account: bool = False, evidence=None, request=None
                 ) -> tuple[VerificationIssue, bool]:
    """File a customer's report. Returns (issue, created).

    A second report on the same order returns the first, unchanged: one case
    per order, enforced by a unique constraint as well as by this check.

    For a provider that reviews reported verifications (TextVerified), a
    screenshot is required, the report goes to the provider at once, and the
    case waits for the provider's decision rather than for staff.
    """
    from apps.orders.models import Order, OrderEvent

    existing = issue_for(order)
    if existing is not None:
        return existing, False

    if reason not in IssueReason.values:
        raise ValidationFailed("Choose what went wrong.")
    if reason == IssueReason.NUMBER_ALREADY_LINKED and not confirmed_existing_account:
        raise ValidationFailed(
            "Confirm that the service asked for an existing password instead of letting you "
            "create an account."
        )
    if not order.phone_number or not order.code_received_at:
        raise Conflict(
            "No code has arrived on this order yet. If none arrives before the timer runs "
            "out, you are refunded automatically."
        )
    if order.refund_status == "COMPLETED":
        raise Conflict("This order has already been refunded.")
    ends = report_window_ends(order)
    if timezone.now() > ends:
        raise Conflict(
            f"Problems can be reported within {describe_window(report_window(order))} of the "
            "code arriving. "
            "Contact support with your order reference."
        )

    provider_reviews = provider_reviews_reports(order.provider.adapter_key)
    # Every report, whichever provider: the screenshot is what a provider (and
    # staff) decide on, and TextVerified will not open a ticket without one.
    screenshots = read_evidence(evidence or [], required=True, formats=REPORT_IMAGE_TYPES)

    ip = (get_client_ip(request) if request else None) or None
    details = " ".join(str(details or "").split())[:500]

    try:
        with transaction.atomic():
            # Serialise reports for this order; the OneToOne backs this up.
            Order.objects.select_for_update().only("id").get(pk=order.pk)
            if VerificationIssue.objects.filter(order=order).exists():
                return VerificationIssue.objects.get(order=order), False

            usage = note_assigned(order)
            record = usage.record if usage else None
            qualification = _qualification(order, reason)
            flags = _risk_flags(order, user, ip)

            issue = VerificationIssue.objects.create(
                reference=issue_reference(),
                order=order,
                user=user,
                number_record=record,
                reason=reason,
                details=details,
                qualifies=all(item["ok"] for item in qualification),
                qualification=qualification,
                risk_flags=flags,
                needs_review=bool(flags),
                ip_address=ip,
                **({"status": IssueStatus.AWAITING_PROVIDER,
                    "provider_decision_due_at": timezone.now() + timedelta(
                        hours=int(settings.VERIFYGH["NUMBER_ISSUE_PROVIDER_DECISION_HOURS"]))}
                   if provider_reviews else {}),
            )
            for data, content_type in screenshots:
                IssueEvidence.objects.create(
                    issue=issue, data=data, content_type=content_type, size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )

            if record is not None:
                NumberRecord.objects.filter(pk=record.pk).update(
                    reports_count=F("reports_count") + 1
                )
                # Only this reason says the *number* has history. Unconfirmed,
                # hence POSSIBLY_REUSED - enough to stop selling it for this
                # service while staff look.
                if (reason == IssueReason.NUMBER_ALREADY_LINKED
                        and record.quality == NumberQuality.NO_ISSUE_REPORTED):
                    _set_quality(record, NumberQuality.POSSIBLY_REUSED)

            OrderEvent.objects.create(
                order=order,
                status=order.status,
                label="Problem reported",
                detail=IssueReason(reason).label,
                is_system=False,
                actor=user,
                metadata={"issue": issue.reference},
            )
    except IntegrityError:
        return VerificationIssue.objects.get(order=order), False

    if any(f["code"] in {"FREQUENT_REPORTER", "REPEAT_REMEDIES"} for f in flags):
        flag(
            user=user,
            kind=SuspiciousActivity.Kind.REFUND_ABUSE,
            level=SuspicionLevel.LOW,
            description="Repeated number-issue reports - review before granting a remedy.",
            evidence={"issue": issue.reference, "flags": [f["code"] for f in flags]},
        )

    record_audit(
        actor=user, action="NUMBER_ISSUE_REPORTED", target=issue, request=request,
        metadata={"order": order.reference, "reason": reason, "needs_review": bool(flags)},
    )
    logger.info(
        "number_issue_reported",
        extra={"issue": issue.reference, "order": order.reference, "reason": reason},
    )
    if provider_reviews:
        from apps.numbers.tasks import send_issue_to_provider

        transaction.on_commit(lambda: send_issue_to_provider.delay(str(issue.pk)))
    _alert_staff_issue_reported(issue, order, user)
    return issue, True


# ---------------------------------------------------------------------------
# Evidence and the provider's review
# ---------------------------------------------------------------------------

_IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

#: What TextVerified's support tickets accept (JPG, JPEG, PNG, GIF), so a
#: customer's screenshot can be attached to the ticket as it is.
REPORT_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif"})
#: Elsewhere (manual top-up proof) WebP is fine too.
DEFAULT_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_TYPE_NAMES = {"image/png": "PNG", "image/jpeg": "JPG", "image/gif": "GIF",
               "image/webp": "WebP"}


def _image_type(data: bytes) -> str | None:
    """Only formats a browser shows safely, recognised by their bytes - never by
    the name or type the upload claims."""
    for magic, content_type in _IMAGE_TYPES:
        if data.startswith(magic):
            return content_type
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_evidence(files, *, required: bool,
                  formats: frozenset = DEFAULT_IMAGE_TYPES) -> list[tuple[bytes, str]]:
    """Check the screenshots attached to a report: (bytes, content type) each."""
    limit = int(settings.VERIFYGH["NUMBER_ISSUE_EVIDENCE_MAX_FILES"])
    max_bytes = int(settings.VERIFYGH["NUMBER_ISSUE_EVIDENCE_MAX_BYTES"])
    files = [f for f in files if f]
    if required and not files:
        raise ValidationFailed(
            "Attach a screenshot that shows the problem and your phone's time - for example, "
            "the app saying the code is wrong or the number is already in use."
        )
    if len(files) > limit:
        raise ValidationFailed(f"Attach at most {limit} screenshots.")
    out = []
    for upload in files:
        if getattr(upload, "size", 0) > max_bytes:
            raise ValidationFailed(
                f"Each screenshot must be {max_bytes // (1024 * 1024)} MB or smaller.")
        data = upload.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValidationFailed(
                f"Each screenshot must be {max_bytes // (1024 * 1024)} MB or smaller.")
        content_type = _image_type(data)
        if content_type not in formats:
            names = [name for kind, name in _TYPE_NAMES.items() if kind in formats]
            raise ValidationFailed(
                f"Screenshots must be {', '.join(names[:-1])} or {names[-1]} images.")
        out.append((data, content_type))
    return out


def provider_reviews_reports(adapter_key: str) -> bool:
    from apps.verification.registry import get_provider

    try:
        return bool(get_provider(adapter_key).tracks_report_refunds)
    except ServiceUnavailable:
        return False


def send_to_provider(issue: VerificationIssue) -> bool:
    """File the report with the provider through its documented report call."""
    from apps.verification.registry import get_provider

    order = issue.order
    try:
        accepted = get_provider(order.provider.adapter_key).report_number_issue(
            order.provider_order_id, issue.reason)
    except Exception:
        logger.warning("provider_issue_report_failed", extra={"issue": issue.reference})
        return False
    if accepted is None:
        return True
    VerificationIssue.objects.filter(pk=issue.pk).update(
        provider_report=(ProviderReportStatus.ACCEPTED if accepted
                         else ProviderReportStatus.REFUSED),
        provider_reported_at=timezone.now(), updated_at=timezone.now(),
    )
    logger.info("provider_issue_reported",
                extra={"issue": issue.reference, "accepted": bool(accepted)})
    return True


def check_provider_decision(issue: VerificationIssue) -> str | None:
    """Ask the provider whether it refunded a reported verification; settle it if so."""
    from apps.verification.registry import get_provider

    if issue.status != IssueStatus.AWAITING_PROVIDER or not issue.order.provider_order_id:
        return None
    try:
        outcome = get_provider(issue.order.provider.adapter_key).report_outcome(
            issue.order.provider_order_id)
    except Exception:
        logger.warning("provider_decision_check_failed", extra={"issue": issue.reference})
        return None
    VerificationIssue.objects.filter(pk=issue.pk).update(
        provider_state=str(outcome or "")[:40], provider_checked_at=timezone.now())
    if outcome == "REFUNDED":
        settle_provider_refund(issue, admin=None,
                               reason="The provider refunded this verification.")
    return outcome


def settle_provider_refund(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    """The provider refunded us for this verification: refund the customer.

    Called by the scheduled check when the provider's verification shows the
    refund, or by staff when the provider refunded through its support instead.
    """
    from apps.orders.models import RefundReason, RefundStatus
    from apps.orders.services import issue_refund

    if issue.status != IssueStatus.AWAITING_PROVIDER:
        raise Conflict("This report is not waiting for the provider.")
    order = paying_order(issue)
    before = {"issue_status": issue.status, "refund_status": order.refund_status}
    if order.refund_status != RefundStatus.COMPLETED:
        order = issue_refund(
            order, reason=RefundReason.NUMBER_UNUSABLE, actor=admin,
            automatic=admin is None, override_delivered=True, provider_refunded=True,
            note=f"{issue.reference}: {reason}",
        )
        if order.refund_status != RefundStatus.COMPLETED:
            raise Conflict("The refund could not be completed. Nothing was credited.")

    if admin is not None:
        record_admin_action(admin=admin, action="ISSUE_PROVIDER_REFUNDED", target=issue,
                            reason=reason, before=before,
                            after={"order": order.reference, "amount": str(order.price)},
                            request=request)
    record_audit(actor=admin, action="NUMBER_ISSUE_PROVIDER_REFUNDED", target=issue,
                 request=request, metadata={"order": order.reference})
    _confirm_number(issue)
    issue = _finish(issue, admin=admin, status=IssueStatus.REFUNDED, note=reason,
                    allowed_from={IssueStatus.AWAITING_PROVIDER},
                    provider_report=ProviderReportStatus.ACCEPTED)
    _notify(issue, "Refund approved",
            f"Our number provider approved your report on {issue.order.reference}. "
            f"{format_ghs(order.price)} is back in your wallet.")
    return issue


def provider_declined(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    """The provider reviewed the report and declined. `reason` is its reply,
    passed on to the customer as the reason."""
    if issue.status != IssueStatus.AWAITING_PROVIDER:
        raise Conflict("This report is not waiting for the provider.")
    reply = str(reason).strip()[:2000]
    record_admin_action(admin=admin, action="ISSUE_PROVIDER_DECLINED", target=issue,
                        reason=reply, before={"status": issue.status},
                        after={"status": "REJECTED"}, request=request)
    issue = _finish(issue, admin=admin, status=IssueStatus.REJECTED,
                    note=f"Provider declined: {reply}",
                    allowed_from={IssueStatus.AWAITING_PROVIDER},
                    provider_report=ProviderReportStatus.REFUSED, customer_reply=reply)
    _unflag_if_unreported(issue)
    _notify(issue, "Your report was not approved",
            f"Our number provider reviewed your report on {issue.order.reference} and did "
            f"not approve a refund. Their reply: {reply}")
    return issue


def mark_ticket_filed(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    """Staff opened a support ticket with the provider; `reason` is its reference."""
    if issue.status != IssueStatus.AWAITING_PROVIDER:
        raise Conflict("This report is not waiting for the provider.")
    ticket = " ".join(str(reason).split())[:80]
    record_admin_action(admin=admin, action="ISSUE_PROVIDER_TICKET", target=issue,
                        reason=ticket, request=request)
    VerificationIssue.objects.filter(pk=issue.pk).update(
        provider_ticket_reference=ticket, provider_ticket_filed_at=timezone.now(),
        updated_at=timezone.now())
    issue.refresh_from_db()
    return issue


def ticket_pack(issue: VerificationIssue) -> dict:
    """Everything staff paste into the provider's support ticket.

    The provider's support is a website form with no API, so a person files it;
    this makes that a copy and a paste. The full phone number stays out - the
    verification ID identifies it in the provider's history.
    """
    order = issue.order
    number = (issue.number_record.number_masked if issue.number_record_id
              else mask(order.phone_number, order.country.dial_code))
    received = timezone.localtime(order.code_received_at).strftime("%d %b %Y %H:%M %Z") \
        if order.code_received_at else "-"
    lines = [
        f"Issue: {IssueReason(issue.reason).label}",
        f"Verification ID: {order.provider_order_id or '-'}",
        f"Number: {number}",
        f"Service: {order.service.name}",
        f"Code received: {received}",
        "",
        f"Our customer reports: {IssueReason(issue.reason).label.lower()}.",
    ]
    if issue.details:
        lines.append(f'Their words: "{issue.details}"')
    lines.append("Screenshot attached. Please review and refund this verification.")
    return {
        "issue_type": IssueReason(issue.reason).label,
        "verification_id": order.provider_order_id,
        "message": "\n".join(lines),
    }


def _alert_staff_issue_reported(issue, order, user) -> None:
    """Tell the people who resolve reports that a customer filed one."""
    from apps.accounts.constants import AdminPermission
    from apps.accounts.services import mask_email
    from apps.notifications.staff import alert_staff

    try:
        said = f' They wrote: "{issue.details[:160]}"' if issue.details else ""
        review = " Flagged for a closer look." if issue.needs_review else ""
        alert_staff(
            permission=AdminPermission.ISSUE_MANAGE,
            event="STAFF_ISSUE_REPORTED",
            title=f"New report {issue.reference}: {IssueReason(issue.reason).label}",
            body=(f"{order.service.name} order {order.reference} by "
                  f"{mask_email(user.email)}.{said}{review}"),
            link=f"/admin/issues?q={issue.reference}",
            reference=issue.reference,
        )
    except Exception:
        # The customer's report is filed either way.
        logger.exception("staff_issue_alert_failed", extra={"issue": issue.reference})


# ---------------------------------------------------------------------------
# Staff decisions
# ---------------------------------------------------------------------------


def _remedy_allowed(name: str) -> None:
    allowed = {r.upper() for r in settings.VERIFYGH["NUMBER_ISSUE_REMEDIES"]}
    if name not in allowed:
        raise Conflict(f"{name.title()} is not part of the current replacement/refund policy.")


def paying_order(issue: VerificationIssue):
    """The order the customer actually paid for.

    A replacement is free, so when a replacement number is itself reported the
    money that can come back is the original purchase's.
    """
    from apps.orders.models import Order

    original_id = (issue.order.metadata or {}).get("replacement_for_order_id")
    if original_id:
        return Order.objects.get(pk=original_id)
    return issue.order


def _replacement_failed(issue: VerificationIssue) -> bool:
    replacement = issue.replacement_order
    return bool(
        replacement is not None
        and replacement.status in {"EXPIRED", "FAILED", "CANCELLED"}
        and not replacement.code_received_at
    )


def _finish(issue: VerificationIssue, *, admin, status: str, note: str,
            allowed_from: set[str], **fields) -> VerificationIssue:
    """Move the case on, but only from the status we checked - two staff acting
    at once cannot both win."""
    changed = VerificationIssue.objects.filter(pk=issue.pk, status__in=allowed_from).update(
        status=status, resolution_note=note[:500], resolved_by=admin,
        resolved_at=timezone.now(), updated_at=timezone.now(), **fields,
    )
    if changed != 1:
        raise Conflict("Someone else has already acted on this report.")
    issue.refresh_from_db()
    return issue


def _confirm_number(issue: VerificationIssue) -> None:
    if issue.number_record and issue.reason == IssueReason.NUMBER_ALREADY_LINKED:
        if issue.number_record.quality != NumberQuality.BLOCKED:
            _set_quality(issue.number_record, NumberQuality.REPORTED_REUSED)


def _notify(issue: VerificationIssue, title: str, body: str) -> None:
    from apps.notifications.services import notify

    notify(issue.user, event="NUMBER_ISSUE_UPDATED", title=title, body=body,
           metadata={"order_reference": issue.order.reference, "issue": issue.reference})


def start_review(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    if issue.status != IssueStatus.OPEN:
        raise Conflict("Only an open report can be moved into review.")
    record_admin_action(admin=admin, action="ISSUE_REVIEW", target=issue, reason=reason,
                        before={"status": issue.status}, after={"status": "IN_REVIEW"},
                        request=request)
    VerificationIssue.objects.filter(pk=issue.pk, status=IssueStatus.OPEN).update(
        status=IssueStatus.IN_REVIEW, updated_at=timezone.now()
    )
    issue.refresh_from_db()
    return issue


def _not_with_provider(issue: VerificationIssue) -> None:
    if issue.status == IssueStatus.AWAITING_PROVIDER:
        raise Conflict(
            "This report is with the provider. The customer is refunded when the provider "
            "refunds it - or record the provider's reply to decline it."
        )


def approve_refund(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    from apps.orders.models import RefundReason, RefundStatus
    from apps.orders.services import issue_refund

    _not_with_provider(issue)
    _remedy_allowed("REFUND")
    allowed_from = set(OPEN_ISSUE_STATUSES)
    if issue.status == IssueStatus.REPLACED and _replacement_failed(issue):
        # The free replacement delivered nothing either; the customer is owed
        # their money.
        allowed_from.add(IssueStatus.REPLACED)
    if issue.status not in allowed_from:
        raise Conflict("This report has already been dealt with.")

    order = paying_order(issue)
    if order.refund_status == RefundStatus.COMPLETED:
        raise Conflict("This order has already been refunded.")

    before = {"issue_status": issue.status, "refund_status": order.refund_status}
    order = issue_refund(
        order, reason=RefundReason.NUMBER_UNUSABLE, actor=admin, automatic=False,
        override_delivered=True, note=f"{issue.reference}: {reason}",
    )
    if order.refund_status != RefundStatus.COMPLETED:
        raise Conflict("The refund could not be completed. Nothing was credited.")

    from apps.orders.models import Refund

    refund = Refund.objects.filter(order=order).first()
    provider = order.provider
    provider_report = ProviderReportStatus.NOT_SUPPORTED
    if _provider_supports_reports(provider.adapter_key):
        # issue_refund already asked the provider for its refund, which for a
        # provider with a report mechanism *is* the report.
        provider_report = (ProviderReportStatus.ACCEPTED
                           if refund and refund.provider_refund_accepted
                           else ProviderReportStatus.REFUSED)

    # Recorded once the money has moved, like every other refund: the ledger
    # entry and the Refund row are the proof, this is who and why.
    record_admin_action(
        admin=admin, action="ISSUE_REFUND", target=issue, reason=reason, before=before,
        after={"order": order.reference, "amount": str(refund.amount if refund else ""),
               "refund": refund.reference if refund else ""},
        request=request,
    )
    _confirm_number(issue)
    issue = _finish(issue, admin=admin, status=IssueStatus.REFUNDED, note=reason,
                    allowed_from=allowed_from, provider_report=provider_report)
    _notify(issue, "Refund approved",
            f"We reviewed your report on {issue.order.reference} and returned "
            f"{format_ghs(order.price)} to your wallet.")
    return issue


def _provider_supports_reports(adapter_key: str) -> bool:
    from apps.verification.registry import get_provider

    try:
        return bool(get_provider(adapter_key).supports_issue_reports)
    except ServiceUnavailable:
        return False


def approve_replacement(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    """Give the customer a new number for the same service, free.

    The new order draws through the same flagged-number screen as any purchase,
    and the reported number is now flagged for this service, so it cannot come
    straight back.
    """
    from apps.orders.models import ACTIVE_ORDER_STATUSES, Order, OrderEvent, OrderStatus
    from apps.orders.services import STATUS_LABELS, resolve_offering
    from apps.orders.tasks import fulfil_order_task
    from apps.pricing.engine import quote_for_offering
    from apps.verification.registry import get_provider

    _not_with_provider(issue)
    _remedy_allowed("REPLACE")
    if issue.status not in OPEN_ISSUE_STATUSES:
        raise Conflict("This report has already been dealt with.")
    if issue.user.is_suspended:
        raise Conflict("The customer's account is suspended.")

    original = issue.order
    platform_cap = int(settings.VERIFYGH["MAX_PLATFORM_ACTIVE_ORDERS"])
    if platform_cap and Order.objects.filter(status__in=ACTIVE_ORDER_STATUSES).count() >= platform_cap:
        raise ServiceUnavailable("We are at capacity right now. Try the replacement again shortly.",
                                 code="PLATFORM_AT_CAPACITY")

    # Raises if the service is no longer sold in that country.
    offering = resolve_offering(original.service.slug, original.country.code)
    # A replacement is free to the customer but not to us: it is bought from
    # our provider balance like any other number. Staff see the real reason.
    from apps.funding.services import check_funding

    funding = check_funding(offering)
    if not funding.ok:
        raise ServiceUnavailable(f"No replacement possible right now: {funding.reason}",
                                 code="PROVIDER_BALANCE_LOW")
    priced = quote_for_offering(offering)
    source = paying_order(issue)

    record_admin_action(
        admin=admin, action="ISSUE_REPLACE", target=issue, reason=reason,
        before={"issue_status": issue.status},
        after={"service": original.service.slug, "country": original.country.code},
        request=request,
    )

    with transaction.atomic():
        replacement, created = Order.objects.get_or_create(
            user=issue.user,
            # One replacement per case, whoever clicks and however often.
            idempotency_key=f"replacement:{issue.pk}",
            defaults={
                "reference": order_reference(),
                "service": offering.service,
                "country": offering.country,
                "provider": offering.provider,
                "provider_service_code": offering.provider_service_code,
                "price": Decimal("0.00"),
                "currency": priced.currency,
                "provider_cost": priced.provider_cost,
                "provider_currency": priced.provider_currency,
                "exchange_rate": priced.exchange_rate,
                "price_breakdown": {**priced.as_dict(), "replacement": True},
                "status": OrderStatus.PROCESSING,
                "expires_at": timezone.now() + timedelta(minutes=offering.ttl_minutes),
                "metadata": {
                    "replacement_for": original.reference,
                    "replacement_for_order_id": str(source.pk),
                    "issue": issue.reference,
                },
            },
        )
        if created:
            OrderEvent.objects.create(
                order=replacement, status=OrderStatus.CREATED,
                label=STATUS_LABELS[OrderStatus.CREATED],
                detail=f"Free replacement for {original.reference}",
            )
            OrderEvent.objects.create(
                order=replacement, status=OrderStatus.PROCESSING,
                label=STATUS_LABELS[OrderStatus.PROCESSING],
                detail="No charge - replacing a number that could not be used.",
            )
        _confirm_number(issue)
        issue = _finish(issue, admin=admin, status=IssueStatus.REPLACED, note=reason,
                        allowed_from=set(OPEN_ISSUE_STATUSES), replacement_order=replacement)
        transaction.on_commit(lambda: fulfil_order_task.delay(str(replacement.pk)))

    # Tell the provider, where it has a documented way to hear it. OnlineSim
    # does not; TextVerified did, but is no longer a supplier.
    provider_report = ProviderReportStatus.NOT_SUPPORTED
    try:
        outcome = get_provider(original.provider.adapter_key).report_number_issue(
            original.provider_order_id, issue.reason
        )
    except Exception:
        logger.warning("provider_issue_report_failed", extra={"issue": issue.reference})
        outcome = False
    if outcome is not None:
        provider_report = (ProviderReportStatus.ACCEPTED if outcome
                           else ProviderReportStatus.REFUSED)
    VerificationIssue.objects.filter(pk=issue.pk).update(provider_report=provider_report)
    issue.refresh_from_db()

    record_audit(actor=admin, action="ORDER_REPLACEMENT_CREATED", target=replacement,
                 request=request, metadata={"issue": issue.reference,
                                            "replaces": original.reference})
    _notify(issue, "Replacement number on its way",
            f"We reviewed your report on {original.reference} and are giving you a new "
            f"{original.service.name} number at no charge: order {replacement.reference}.")
    return issue


def _unflag_if_unreported(issue: VerificationIssue) -> None:
    """Un-flag the number, unless another report still stands against it."""
    record = issue.number_record
    if record is not None and record.quality == NumberQuality.POSSIBLY_REUSED:
        still_reported = VerificationIssue.objects.filter(
            number_record=record, reason=IssueReason.NUMBER_ALREADY_LINKED,
            status__in=[*OPEN_ISSUE_STATUSES, IssueStatus.REFUNDED, IssueStatus.REPLACED],
        ).exclude(pk=issue.pk).exists()
        if not still_reported:
            _set_quality(record, NumberQuality.NO_ISSUE_REPORTED)


def reject_claim(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    _not_with_provider(issue)
    if issue.status not in OPEN_ISSUE_STATUSES:
        raise Conflict("This report has already been dealt with.")
    record_admin_action(admin=admin, action="ISSUE_REJECT", target=issue, reason=reason,
                        before={"status": issue.status}, after={"status": "REJECTED"},
                        request=request)
    issue = _finish(issue, admin=admin, status=IssueStatus.REJECTED, note=reason,
                    allowed_from=set(OPEN_ISSUE_STATUSES))
    _unflag_if_unreported(issue)

    _notify(issue, "We've reviewed your report",
            f"We looked into your report on {issue.order.reference} and could not confirm "
            "the number was unusable. Contact support if you'd like us to look again.")
    return issue


def mark_resolved(issue, *, admin, reason: str, request=None) -> VerificationIssue:
    if issue.status not in OPEN_ISSUE_STATUSES:
        raise Conflict("This report has already been dealt with.")
    record_admin_action(admin=admin, action="ISSUE_RESOLVE", target=issue, reason=reason,
                        before={"status": issue.status}, after={"status": "RESOLVED"},
                        request=request)
    issue = _finish(issue, admin=admin, status=IssueStatus.RESOLVED, note=reason,
                    allowed_from=set(OPEN_ISSUE_STATUSES))
    _notify(issue, "Your report is resolved",
            f"We've closed your report on {issue.order.reference}.")
    return issue


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def metrics(days: int = 30) -> dict:
    """Counts for the dashboard.

    Every rate here is *customer-reported*: reports divided by delivered
    orders. It measures what customers told us, not a confirmed failure rate of
    any provider or number pool, and the labels say so.
    """
    from apps.orders.models import Order

    since = timezone.now() - timedelta(days=days)
    orders = Order.objects.filter(created_at__gte=since)
    issues = VerificationIssue.objects.filter(created_at__gte=since)

    purchased = orders.exclude(phone_number="").count()
    delivered = orders.filter(code_received_at__isnull=False).count()
    reuse = issues.filter(reason=IssueReason.NUMBER_ALREADY_LINKED)

    def rate(part: int, whole: int) -> float | None:
        return round(100 * part / whole, 1) if whole else None

    def breakdown(field: str, label: str) -> list[dict]:
        delivered_by = dict(
            orders.filter(code_received_at__isnull=False)
            .values_list(field).annotate(n=Count("id")).values_list(field, "n")
        )
        reports_by = dict(
            reuse.values_list(f"order__{field}").annotate(n=Count("id"))
            .values_list(f"order__{field}", "n")
        )
        names = dict(
            orders.values_list(field, label).distinct()
        )
        names.update(dict(reuse.values_list(f"order__{field}", f"order__{label}").distinct()))
        rows = []
        for key in set(delivered_by) | set(reports_by):
            d, r = delivered_by.get(key, 0), reports_by.get(key, 0)
            rows.append({"name": names.get(key, "?"), "delivered": d,
                         "possible_reuse_reports": r, "reported_rate_percent": rate(r, d)})
        return sorted(rows, key=lambda row: (-row["possible_reuse_reports"], -row["delivered"]))

    return {
        "days": days,
        "numbers_purchased": purchased,
        "sms_received": delivered,
        "reports_total": issues.count(),
        "reports_by_reason": {
            reason: issues.filter(reason=reason).count() for reason in IssueReason.values
        },
        "possible_reuse_reports": reuse.count(),
        "possible_reuse_rate_percent": rate(reuse.count(), delivered),
        "open_cases": issues.filter(status__in=OPEN_ISSUE_STATUSES).count(),
        "needs_review": issues.filter(status__in=OPEN_ISSUE_STATUSES, needs_review=True).count(),
        "refunded_orders": issues.filter(status=IssueStatus.REFUNDED).count(),
        "refunded_amount": str(
            sum((r.amount for r in _issue_refunds(since)), Decimal("0.00"))
        ),
        "replacement_orders": issues.filter(status=IssueStatus.REPLACED).count(),
        "rejected": issues.filter(status=IssueStatus.REJECTED).count(),
        "numbers_turned_away": NumberUsage.objects.filter(
            disposition=UsageDisposition.EXCLUDED, created_at__gte=since
        ).count(),
        "flagged_numbers": NumberRecord.objects.filter(quality__in=EXCLUDED_QUALITIES).count(),
        "by_provider": breakdown("provider_id", "provider__name"),
        "by_service": breakdown("service_id", "service__name"),
        "note": "Rates are customer reports divided by orders that received a code. "
                "They are not confirmed provider failure rates.",
    }


def _issue_refunds(since):
    from apps.orders.models import Refund, RefundReason

    return Refund.objects.filter(
        reason=RefundReason.NUMBER_UNUSABLE, status="COMPLETED", created_at__gte=since
    )
