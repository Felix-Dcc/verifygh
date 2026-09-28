"""Number quality: what we know about the numbers we hand out.

Written after a customer bought a number for TikTok, received the code, and
was asked for an existing password instead of being allowed to create an
account. That usually means someone registered the number with TikTok before
us - numbers are recycled through the provider's pool - but it is not proof.
Nothing we can call tells us a number's history with a third-party service:

* OnlineSim documents no history, reuse or report endpoint. `getState` covers
  active operations only, `getNum`'s `reject` takes digit *masks* of an
  undocumented format, and `setOperationOk`'s `ban=1` is for wrongly formatted
  numbers and only works while no SMS has arrived.
* TextVerified documents `POST /verifications/{id}/report` for issues such as
  "number already in use". It is a report, not a lookup: it tells us nothing
  in advance about any number.

So the evidence here is what customers tell us, weighed by staff. The words in
this module are chosen to match: a reported number is POSSIBLY_REUSED, not
"reused", until a person has looked at it.

Three tables:

* `NumberRecord` - one row per (provider, number, service). A number that is
  spent on TikTok may be perfectly good for Telegram, so quality is tracked per
  service and a report for one never blocks the others.
* `NumberUsage` - one row every time a provider hands us a number: the history
  of each number, including the ones we turned away because they were flagged.
* `VerificationIssue` - a customer's report about an order, and what staff
  decided to do about it.

The number itself is stored as a keyed hash plus a masked form. The order keeps
the full number (the customer needs it on their screen); this long-lived
history does not need it to match a number again, so it does not keep it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.catalog.models import Provider, Service
from apps.common.models import BaseModel


class NumberQuality(models.TextChoices):
    NO_ISSUE_REPORTED = "NO_ISSUE_REPORTED", "No issue reported"
    #: A customer said the service treated the number as already registered.
    #: Unconfirmed. Enough to stop selling it for that service until reviewed.
    POSSIBLY_REUSED = "POSSIBLY_REUSED", "Possibly reused"
    #: Staff reviewed a report and agreed.
    REPORTED_REUSED = "REPORTED_REUSED", "Reported reused (confirmed by staff)"
    #: The number itself is unusable for every service - only on evidence that
    #: goes beyond one service's behaviour, such as the provider saying so.
    BLOCKED = "BLOCKED", "Blocked for all services"


#: Qualities that keep a number out of future orders for the same service.
EXCLUDED_QUALITIES = frozenset(
    {NumberQuality.POSSIBLY_REUSED, NumberQuality.REPORTED_REUSED, NumberQuality.BLOCKED}
)


class NumberRecord(BaseModel):
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="number_records")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="number_records")
    #: HMAC-SHA256 of the digits, keyed by the server - see services.fingerprint.
    fingerprint = models.CharField(max_length=64, db_index=True)
    number_masked = models.CharField(max_length=32)

    quality = models.CharField(
        max_length=20, choices=NumberQuality.choices,
        default=NumberQuality.NO_ISSUE_REPORTED, db_index=True,
    )
    quality_changed_at = models.DateTimeField(null=True, blank=True)

    times_issued = models.PositiveIntegerField(default=0)
    reports_count = models.PositiveIntegerField(default=0)
    first_issued_at = models.DateTimeField(null=True, blank=True)
    last_issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "numbers_record"
        ordering = ["-last_issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "service", "fingerprint"], name="number_record_unique"
            ),
            models.CheckConstraint(
                check=models.Q(quality__in=[c for c, _ in NumberQuality.choices]),
                name="number_record_quality_valid",
            ),
        ]
        indexes = [models.Index(fields=["provider", "fingerprint"])]

    def __str__(self) -> str:
        return f"{self.number_masked} {self.service_id} [{self.quality}]"


class UsageDisposition(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Given to a customer"
    #: Came back from the provider but was flagged for this service, so we
    #: released it and drew another.
    EXCLUDED = "EXCLUDED", "Turned away (flagged)"


class NumberUsage(BaseModel):
    """One number, one time the provider gave it to us."""

    record = models.ForeignKey(NumberRecord, on_delete=models.PROTECT, related_name="usages")
    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="number_usages"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="number_usages"
    )
    provider_order_id = models.CharField(max_length=128, blank=True, default="")
    disposition = models.CharField(
        max_length=10, choices=UsageDisposition.choices, default=UsageDisposition.ASSIGNED
    )
    acquired_at = models.DateTimeField()
    assigned_at = models.DateTimeField(null=True, blank=True)
    #: For EXCLUDED numbers: whether the provider accepted the release yet.
    released = models.BooleanField(default=False)

    class Meta:
        db_table = "numbers_usage"
        ordering = ["-acquired_at"]
        indexes = [models.Index(fields=["record", "-acquired_at"])]


class IssueReason(models.TextChoices):
    NUMBER_ALREADY_LINKED = "NUMBER_ALREADY_LINKED", "Number already linked to an account"
    SMS_NOT_RECEIVED = "SMS_NOT_RECEIVED", "Didn't receive SMS"
    OTP_DID_NOT_WORK = "OTP_DID_NOT_WORK", "OTP didn't work"
    SERVICE_REJECTED_NUMBER = "SERVICE_REJECTED_NUMBER", "Service rejected the number"
    OTHER = "OTHER", "Other"


class IssueStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_REVIEW = "IN_REVIEW", "In review"
    REFUNDED = "REFUNDED", "Refunded"
    REPLACED = "REPLACED", "Replaced"
    REJECTED = "REJECTED", "Not approved"
    RESOLVED = "RESOLVED", "Resolved"


#: A case staff can still act on.
OPEN_ISSUE_STATUSES = frozenset({IssueStatus.OPEN, IssueStatus.IN_REVIEW})


class ProviderReportStatus(models.TextChoices):
    NOT_SUPPORTED = "NOT_SUPPORTED", "Provider has no report mechanism"
    NOT_SENT = "NOT_SENT", "Not sent"
    ACCEPTED = "ACCEPTED", "Accepted by provider"
    REFUSED = "REFUSED", "Refused by provider"


class VerificationIssue(BaseModel):
    """A customer's report about an order, and its resolution.

    One per order, enforced by the database: a second report on the same order
    returns this one, so double-tapping "Report" cannot open two cases or,
    later, two refunds.
    """

    reference = models.CharField(max_length=20, unique=True, db_index=True)
    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="issue"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="verification_issues"
    )
    number_record = models.ForeignKey(
        NumberRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="issues"
    )

    reason = models.CharField(max_length=32, choices=IssueReason.choices, db_index=True)
    #: The customer's own words. Capped, and the form tells them never to put a
    #: password or code in it.
    details = models.CharField(max_length=500, blank=True, default="")

    status = models.CharField(
        max_length=10, choices=IssueStatus.choices, default=IssueStatus.OPEN, db_index=True
    )
    #: Whether the report fits the replacement/refund policy, with the reasons,
    #: worked out when it was filed. Advice for staff, never an automatic payout.
    qualifies = models.BooleanField(default=False)
    qualification = models.JSONField(default=list, blank=True)
    #: Patterns worth a second look. Never grounds to refuse on their own.
    risk_flags = models.JSONField(default=list, blank=True)
    needs_review = models.BooleanField(default=False, db_index=True)

    resolution_note = models.CharField(max_length=500, blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="resolved_verification_issues",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    replacement_order = models.OneToOneField(
        "orders.Order", null=True, blank=True, on_delete=models.PROTECT,
        related_name="replaces_issue",
    )

    provider_report = models.CharField(
        max_length=16, choices=ProviderReportStatus.choices,
        default=ProviderReportStatus.NOT_SENT,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "numbers_verification_issue"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=[c for c, _ in IssueStatus.choices]),
                name="verification_issue_status_valid",
            ),
            models.CheckConstraint(
                check=models.Q(reason__in=[c for c, _ in IssueReason.choices]),
                name="verification_issue_reason_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.reason} [{self.status}]"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ISSUE_STATUSES
