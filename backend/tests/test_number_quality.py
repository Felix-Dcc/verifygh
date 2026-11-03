"""Reported numbers: history, the flagged-number screen, reports and remedies.

Reproduces the TikTok case - a code arrives, the customer uses it, and the
service asks for an existing password - and follows it through every outcome
staff can choose, checking the ledger and the audit trail at each step.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AdminAction, AuditLog, SuspiciousActivity
from apps.numbers import services as numbers
from apps.numbers.models import (
    IssueStatus,
    NumberQuality,
    NumberRecord,
    NumberUsage,
    UsageDisposition,
    VerificationIssue,
)
from apps.orders.models import Order, OrderStatus, Refund, RefundReason, RefundStatus
from apps.orders.services import poll_order
from apps.verification import mock as verification_mock
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

NUMBER = "+15550104234"
OTHER_NUMBER = "+15550109999"
THIRD_NUMBER = "+15550107777"
LINKED = {"reason": "NUMBER_ALREADY_LINKED", "confirmed_existing_account": True}

_capture = None


@pytest.fixture(autouse=True)
def _hooks(django_capture_on_commit_callbacks):
    global _capture
    _capture = django_capture_on_commit_callbacks
    yield


def sign_in(account: User, password: str) -> APIClient:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": account.email, "password": password},
                           format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def customer(user):
    return sign_in(user, "Correct-Horse-Battery-1")


@pytest.fixture
def staff(admin_user):
    return sign_in(admin_user, "Correct-Horse-Battery-3")


def buy(client, number: str | None = NUMBER, service="instagram") -> Order:
    verification_mock.force_scenario("HAPPY")
    if number:
        verification_mock.force_numbers([number])
    with _capture(execute=True):
        response = client.post("/api/v1/orders/", {"service": service, "country": "US"},
                               format="json")
    assert response.status_code == 201, response.data
    return Order.objects.get(reference=response.data["reference"])


def deliver(order: Order) -> Order:
    verification_mock.fast_forward(order.provider_order_id, 30)
    order = poll_order(Order.objects.get(pk=order.pk))
    assert order.status == OrderStatus.CODE_RECEIVED
    return order


def report(client, order, body=LINKED):
    # Every report carries a screenshot, as the site now requires.
    return client.post(f"/api/v1/orders/{order.reference}/report/",
                       {**body, "evidence": [screenshot()]}, format="multipart")


def act(client, issue_ref, verb, reason="Checked the report against the number history"):
    with _capture(execute=True):
        return client.post(f"/api/v1/admin/number-issues/{issue_ref}/{verb}/",
                           {"reason": reason}, format="json")


@pytest.fixture
def delivered(user, customer, catalog, funded_wallet):
    """Steps 1-3: purchase, SMS arrives, customer marks it complete."""
    funded_wallet(user, "200.00")
    order = deliver(buy(customer))
    assert customer.post(f"/api/v1/orders/{order.reference}/complete/", {},
                         format="json").status_code == 200
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED
    return order


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_every_assigned_number_gets_a_history_row(delivered):
    usage = NumberUsage.objects.get(order=delivered)

    assert usage.disposition == UsageDisposition.ASSIGNED
    assert usage.record.times_issued == 1
    assert usage.record.quality == NumberQuality.NO_ISSUE_REPORTED
    assert usage.record.number_masked == "+1 *** *** 4234"
    # The history keeps a keyed hash, never the number.
    assert NUMBER not in usage.record.fingerprint
    assert "5550104234" not in str(NumberRecord.objects.values().get())


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_reporting_a_linked_number_opens_a_case_and_flags_it_possibly_reused(
    user, customer, delivered
):
    response = report(customer, delivered)

    assert response.status_code == 201, response.data
    assert "flagged this number for review" in response.data["message"]
    issue = VerificationIssue.objects.get(order=delivered)
    assert issue.status == IssueStatus.OPEN
    assert issue.qualifies is True
    # Possibly, not definitely: a customer's word is not proof.
    assert issue.number_record.quality == NumberQuality.POSSIBLY_REUSED
    # A report moves no money.
    assert delivered.refund_status == RefundStatus.NONE
    assert not Refund.objects.filter(order=delivered).exists()
    assert AuditLog.objects.filter(action="NUMBER_ISSUE_REPORTED").exists()

    detail = customer.get(f"/api/v1/orders/{delivered.reference}/").data
    assert detail["issue"]["reference"] == issue.reference
    assert detail["can_report"] is False


def test_the_linked_reason_needs_the_password_screen_confirmed(customer, delivered):
    response = report(customer, delivered, {"reason": "NUMBER_ALREADY_LINKED"})

    assert response.status_code == 400
    assert not VerificationIssue.objects.exists()


def test_a_second_report_on_the_same_order_returns_the_first(customer, delivered):
    first = report(customer, delivered)
    second = report(customer, delivered, {"reason": "OTHER", "details": "again"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["reference"] == first.data["reference"]
    assert VerificationIssue.objects.count() == 1
    assert NumberRecord.objects.get().reports_count == 1


def test_other_reasons_open_a_case_without_flagging_the_number(customer, delivered):
    report(customer, delivered, {"reason": "OTP_DID_NOT_WORK"})

    issue = VerificationIssue.objects.get()
    assert issue.qualifies is False  # staff look case by case
    assert issue.number_record.quality == NumberQuality.NO_ISSUE_REPORTED


def test_an_order_with_no_code_cannot_be_reported(user, customer, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    order = buy(customer)  # waiting; no code yet

    response = report(customer, order)

    assert response.status_code == 409
    assert "refunded automatically" in response.data["error"]["message"]


def test_reports_close_after_the_window(customer, delivered, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "NUMBER_ISSUE_REPORT_WINDOW_HOURS": 0}

    assert report(customer, delivered).status_code == 409


def test_nobody_can_report_someone_elses_order(delivered, other_user):
    stranger = sign_in(other_user, "Correct-Horse-Battery-2")

    assert report(stranger, delivered).status_code == 404


# ---------------------------------------------------------------------------
# Admin: the case list
# ---------------------------------------------------------------------------


def test_admin_sees_the_case_with_a_masked_number(customer, staff, delivered):
    report(customer, delivered)

    listing = staff.get("/api/v1/admin/number-issues/").data
    row = listing["results"][0]
    assert row["order_reference"] == delivered.reference
    assert row["number_masked"] == "+1 *** *** 4234"
    assert row["status"] == "OPEN"
    assert row["service_name"] == delivered.service.name
    assert NUMBER not in str(listing)

    detail = staff.get(f"/api/v1/admin/number-issues/{row['reference']}/").data
    assert detail["history"]["quality"] == NumberQuality.POSSIBLY_REUSED
    assert detail["history"]["provider_history_available"] is False
    assert detail["timeline"]["sms_received_at"] is not None
    assert NUMBER not in str(detail)


def test_the_open_filter_counts_every_case_still_waiting(customer, staff, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()

    def open_count():
        return staff.get("/api/v1/admin/number-issues/?status=open&page_size=1").data[
            "pagination"]["count"]

    for status in ("OPEN", "IN_REVIEW", "AWAITING_PROVIDER"):
        VerificationIssue.objects.filter(pk=issue.pk).update(status=status)
        assert open_count() == 1, status
    for status in ("REFUNDED", "REPLACED", "REJECTED", "RESOLVED"):
        VerificationIssue.objects.filter(pk=issue.pk).update(status=status)
        assert open_count() == 0, status


def test_customers_cannot_reach_the_admin_endpoints(customer, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()

    assert customer.get("/api/v1/admin/number-issues/").status_code == 403
    assert act(customer, issue.reference, "refund").status_code == 403


def test_support_can_view_but_not_decide(customer, delivered, support_user):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()
    support = sign_in(support_user, "Correct-Horse-Battery-4")

    assert support.get("/api/v1/admin/number-issues/").status_code == 200
    for verb in ("refund", "replace", "reject", "resolve", "review"):
        assert act(support, issue.reference, verb).status_code == 403, verb
    assert not AdminAction.objects.exists()


# ---------------------------------------------------------------------------
# Admin: replacement
# ---------------------------------------------------------------------------


def test_replacement_is_free_avoids_the_reported_number_and_is_audited(
    user, customer, staff, delivered
):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()
    wallet = get_or_create_wallet(user)
    balance_before = wallet.balance
    entries_before = WalletLedgerEntry.objects.filter(wallet=wallet).count()

    # The provider offers the reported number first, then a different one.
    verification_mock.force_numbers([NUMBER, OTHER_NUMBER])
    response = act(staff, issue.reference, "replace")

    assert response.status_code == 200, response.data
    issue.refresh_from_db()
    assert issue.status == IssueStatus.REPLACED
    replacement = issue.replacement_order
    replacement.refresh_from_db()
    # 8. a replacement order exists, for the same service, at no charge
    assert replacement.service_id == delivered.service_id
    assert replacement.price == Decimal("0.00")
    assert replacement.metadata["replacement_for"] == delivered.reference
    # 9. the reported number was turned away and a different one given
    assert replacement.phone_number == OTHER_NUMBER
    turned_away = NumberUsage.objects.get(order=replacement, disposition=UsageDisposition.EXCLUDED)
    assert turned_away.record == issue.number_record
    assert turned_away.released is True
    # Staff agreed, so the flag firms up.
    assert issue.number_record.quality == NumberQuality.REPORTED_REUSED
    # 11. no money moved
    wallet.refresh_from_db()
    assert wallet.balance == balance_before
    assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == entries_before
    assert verify_wallet_integrity(wallet)["ok"] is True
    # 12. audited
    action = AdminAction.objects.get(action="ISSUE_REPLACE")
    assert action.target_id == str(issue.pk)
    assert action.reason
    assert AuditLog.objects.filter(action="ORDER_REPLACEMENT_CREATED").exists()
    # The mock documents a report mechanism, so the provider heard about it.
    assert issue.provider_report == "ACCEPTED"

    # The customer sees the replacement.
    detail = customer.get(f"/api/v1/orders/{replacement.reference}/").data
    assert detail["replacement_for"] == delivered.reference


def test_replacing_twice_makes_one_replacement(customer, staff, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()
    verification_mock.force_numbers([OTHER_NUMBER])

    assert act(staff, issue.reference, "replace").status_code == 200
    assert act(staff, issue.reference, "replace").status_code == 409
    assert Order.objects.filter(metadata__replacement_for=delivered.reference).count() == 1


def test_a_failed_replacement_can_still_be_refunded(user, customer, staff, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()
    verification_mock.force_scenario("NO_STOCK")
    act(staff, issue.reference, "replace")
    issue.refresh_from_db()
    assert issue.replacement_order.status in {OrderStatus.FAILED, OrderStatus.REFUNDED}

    response = act(staff, issue.reference, "refund")

    assert response.status_code == 200, response.data
    delivered.refresh_from_db()
    assert delivered.refund_status == RefundStatus.COMPLETED


# ---------------------------------------------------------------------------
# Admin: refund
# ---------------------------------------------------------------------------


def test_approved_refund_credits_the_wallet_once_through_the_ledger(
    user, customer, staff, delivered
):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()
    wallet = get_or_create_wallet(user)
    before = wallet.balance

    response = act(staff, issue.reference, "refund")

    assert response.status_code == 200, response.data
    issue.refresh_from_db()
    assert issue.status == IssueStatus.REFUNDED
    # 10. recorded as a refund of this order, for its price, with the right reason
    refund = Refund.objects.get(order=delivered)
    assert refund.amount == delivered.price
    assert refund.reason == RefundReason.NUMBER_UNUSABLE
    assert refund.is_automatic is False
    # 11. the ledger agrees with the balance
    wallet.refresh_from_db()
    assert wallet.balance == before + delivered.price
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type=LedgerEntryType.REFUND
    ).count() == 1
    assert verify_wallet_integrity(wallet)["ok"] is True
    # 12. audited, with the reason
    assert AdminAction.objects.filter(action="ISSUE_REFUND", target_id=str(issue.pk)).exists()
    assert AuditLog.objects.filter(action="ORDER_REFUNDED").exists()

    # A second approval cannot pay twice.
    assert act(staff, issue.reference, "refund").status_code == 409
    wallet.refresh_from_db()
    assert wallet.balance == before + delivered.price


def test_a_completed_order_is_still_not_refundable_outside_a_case(staff, delivered):
    """The override is for upheld reports only; the ordinary refund button keeps
    refusing delivered orders."""
    response = staff.post(f"/api/v1/admin/orders/{delivered.reference}/refund/",
                          {"reason": "Customer asked nicely"}, format="json")

    assert response.status_code == 409
    delivered.refresh_from_db()
    assert delivered.refund_status == RefundStatus.NONE


def test_the_policy_can_switch_refunds_off(customer, staff, delivered, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "NUMBER_ISSUE_REMEDIES": ["REPLACE"]}
    report(customer, delivered)
    issue = VerificationIssue.objects.get()

    assert act(staff, issue.reference, "refund").status_code == 409
    assert not Refund.objects.exists()


# ---------------------------------------------------------------------------
# Admin: reject and resolve
# ---------------------------------------------------------------------------


def test_rejecting_clears_an_unconfirmed_flag(customer, staff, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()

    assert act(staff, issue.reference, "review").status_code == 200
    assert act(staff, issue.reference, "reject").status_code == 200

    issue.refresh_from_db()
    assert issue.status == IssueStatus.REJECTED
    assert issue.number_record.quality == NumberQuality.NO_ISSUE_REPORTED
    assert not Refund.objects.exists()
    assert set(AdminAction.objects.values_list("action", flat=True)) == {
        "ISSUE_REVIEW", "ISSUE_REJECT"
    }
    # A decided case cannot be decided again.
    assert act(staff, issue.reference, "refund").status_code == 409


def test_an_admin_action_needs_a_reason(customer, staff, delivered):
    report(customer, delivered)
    issue = VerificationIssue.objects.get()

    response = act(staff, issue.reference, "resolve", reason="")

    assert response.status_code == 400
    assert VerificationIssue.objects.get().status == IssueStatus.OPEN


# ---------------------------------------------------------------------------
# The screen on future purchases
# ---------------------------------------------------------------------------


def test_a_flagged_number_is_not_sold_again_for_that_service(
    user, customer, delivered, other_user, funded_wallet
):
    report(customer, delivered)
    funded_wallet(other_user, "200.00")
    buyer = sign_in(other_user, "Correct-Horse-Battery-2")

    verification_mock.force_numbers([NUMBER, OTHER_NUMBER])
    order = buy(buyer, number=None)

    assert order.phone_number == OTHER_NUMBER
    assert NumberUsage.objects.filter(order=order, disposition="EXCLUDED").count() == 1


def test_a_flag_for_one_service_does_not_block_another(
    user, customer, delivered, funded_wallet
):
    report(customer, delivered)  # flagged for Instagram only

    order = buy(customer, number=NUMBER, service="telegram")

    assert order.phone_number == NUMBER
    assert NumberRecord.objects.get(service=order.service).quality == \
        NumberQuality.NO_ISSUE_REPORTED


def test_when_only_flagged_numbers_come_back_the_customer_is_refunded(
    user, customer, delivered, settings
):
    report(customer, delivered)
    settings.VERIFYGH = {**settings.VERIFYGH, "NUMBER_QUALITY_MAX_REDRAWS": 1}
    wallet = get_or_create_wallet(user)
    before = wallet.balance

    verification_mock.force_numbers([NUMBER, NUMBER])
    order = buy(customer, number=None)

    order.refresh_from_db()
    assert order.status == OrderStatus.REFUNDED
    assert order.phone_number == ""
    wallet.refresh_from_db()
    assert wallet.balance == before
    assert verify_wallet_integrity(wallet)["ok"] is True


# ---------------------------------------------------------------------------
# Abuse signals flag, never refuse
# ---------------------------------------------------------------------------


def test_frequent_reporters_are_flagged_for_review_not_refused(
    user, customer, catalog, funded_wallet, settings
):
    settings.VERIFYGH = {**settings.VERIFYGH, "NUMBER_ISSUE_REVIEW_THRESHOLD": 2,
                         "MAX_ORDERS_PER_DAY": 50}
    funded_wallet(user, "500.00")
    numbers_ = ["+15550100001", "+15550100002"]
    issues = []
    for number in numbers_:
        order = deliver(buy(customer, number=number))
        response = report(customer, order)
        assert response.status_code == 201  # never refused
        issues.append(VerificationIssue.objects.get(order=order))

    codes = [{f["code"] for f in issue.risk_flags} for issue in issues]
    assert "FREQUENT_REPORTER" not in codes[0]
    assert "FREQUENT_REPORTER" in codes[1]
    assert issues[1].needs_review is True
    # The fixture account is minutes old, which is itself a signal.
    assert "NEW_ACCOUNT" in codes[0]
    assert SuspiciousActivity.objects.filter(
        user=user, kind=SuspiciousActivity.Kind.REFUND_ABUSE
    ).exists()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_count_reports_as_reports(customer, staff, delivered):
    report(customer, delivered)

    data = staff.get("/api/v1/admin/number-issues-metrics/").data

    assert data["numbers_purchased"] == 1
    assert data["sms_received"] == 1
    assert data["possible_reuse_reports"] == 1
    assert data["possible_reuse_rate_percent"] == 100.0
    assert data["by_service"][0]["name"] == delivered.service.name
    assert "not confirmed provider failure rates" in data["note"]


def test_masking():
    assert numbers.mask("+15550104234", "+1") == "+1 *** *** 4234"
    assert numbers.mask("+233241234567", "+233") == "+233 *** *** 4567"
    assert numbers.fingerprint("+1 555 010 4234") == numbers.fingerprint("15550104234")


def test_a_report_alerts_the_staff_who_resolve_reports(user, customer, delivered, admin_user,
                                                       support_user):
    from django.core import mail

    from apps.notifications.models import Channel, Notification

    with _capture(execute=True):
        response = report(customer, delivered, {**LINKED, "details": "It asked for a password"})
    assert response.status_code == 201, response.data
    issue = VerificationIssue.objects.get(order=delivered)

    alerts = Notification.objects.filter(event="STAFF_ISSUE_REPORTED")
    assert set(alerts.values_list("user_id", flat=True)) == {admin_user.pk}
    assert {a.channel for a in alerts} == {Channel.IN_APP, Channel.EMAIL}
    alert = alerts.get(channel=Channel.IN_APP)
    assert issue.reference in alert.title
    assert delivered.reference in alert.body and "asked for a password" in alert.body
    assert alert.metadata["admin_link"] == f"/admin/issues?q={issue.reference}"
    assert any(issue.reference in m.subject for m in mail.outbox)
    # Reporting the same order again opens nothing new, so pages no one again.
    with _capture(execute=True):
        report(customer, delivered)
    assert Notification.objects.filter(event="STAFF_ISSUE_REPORTED").count() == 2


# ---------------------------------------------------------------------------
# Reports a provider reviews (TextVerified): screenshot, sent at once, and the
# customer refunded only when the provider refunds us
# ---------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def screenshot(data: bytes = PNG, name: str = "shot.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, data, content_type="image/png")


@pytest.fixture
def reviewing(monkeypatch):
    """The mock provider behaving like TextVerified: it reviews reports."""
    state = {"outcome": "PENDING", "reports": []}
    cls = verification_mock.MockVerificationProvider
    monkeypatch.setattr(cls, "tracks_report_refunds", True, raising=False)
    monkeypatch.setattr(cls, "report_outcome",
                        lambda self, provider_order_id: state["outcome"], raising=False)
    original = cls.report_number_issue

    def recording(self, provider_order_id, reason):
        state["reports"].append(provider_order_id)
        return original(self, provider_order_id, reason)

    monkeypatch.setattr(cls, "report_number_issue", recording)
    return state


def report_with_evidence(client, order, files=None, body=LINKED):
    payload = {**body, "evidence": files if files is not None else [screenshot()]}
    with _capture(execute=True):
        return client.post(f"/api/v1/orders/{order.reference}/report/", payload,
                           format="multipart")


def balance(user) -> Decimal:
    return get_or_create_wallet(user).balance


def test_a_report_the_provider_reviews_needs_a_screenshot(customer, delivered, reviewing):
    response = report_with_evidence(customer, delivered, files=[])
    assert response.status_code == 400
    assert not VerificationIssue.objects.exists()


def test_only_real_images_are_accepted_as_evidence(customer, delivered, reviewing):
    response = report_with_evidence(customer, delivered,
                                    files=[screenshot(b"<html>not an image</html>", "x.png")])
    assert response.status_code == 400
    assert not VerificationIssue.objects.exists()


def test_the_report_goes_to_the_provider_at_once_and_waits_for_it(
        user, customer, delivered, reviewing):
    before = balance(user)
    response = report_with_evidence(customer, delivered)
    assert response.status_code == 201, response.data

    issue = VerificationIssue.objects.get(order=delivered)
    assert issue.status == IssueStatus.AWAITING_PROVIDER
    assert reviewing["reports"] == [delivered.provider_order_id]
    assert issue.provider_report == "ACCEPTED" and issue.provider_reported_at
    assert issue.provider_decision_due_at > issue.created_at
    assert issue.evidence.count() == 1
    assert balance(user) == before  # nothing moves until the provider decides
    assert response.data["decision_due_at"]
    assert "number provider" in response.data["message"]


def test_staff_cannot_refund_replace_or_reject_while_the_provider_decides(
        customer, staff, delivered, reviewing):
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    for verb in ("refund", "replace", "reject"):
        assert act(staff, issue.reference, verb).status_code == 409, verb
    issue.refresh_from_db()
    assert issue.status == IssueStatus.AWAITING_PROVIDER


def test_the_customer_is_refunded_when_the_provider_refunds(user, customer, delivered,
                                                             reviewing):
    from apps.numbers.tasks import check_provider_refunds

    report_with_evidence(customer, delivered)
    before = balance(user)

    reviewing["outcome"] = "PENDING"
    with _capture(execute=True):
        check_provider_refunds()
    assert VerificationIssue.objects.get(order=delivered).status == IssueStatus.AWAITING_PROVIDER

    reviewing["outcome"] = "REFUNDED"
    with _capture(execute=True):
        check_provider_refunds()
        check_provider_refunds()  # a second run must not refund twice

    issue = VerificationIssue.objects.get(order=delivered)
    assert issue.status == IssueStatus.REFUNDED
    assert balance(user) == before + delivered.price
    refund = Refund.objects.get(order=delivered)
    assert refund.provider_refund_accepted is True
    assert WalletLedgerEntry.objects.filter(entry_type=LedgerEntryType.REFUND).count() == 1
    assert verify_wallet_integrity(get_or_create_wallet(user))["ok"]


def test_a_claim_past_its_expected_decision_stays_open(customer, delivered, reviewing):
    from datetime import timedelta

    from django.utils import timezone

    from apps.numbers.tasks import check_provider_refunds

    report_with_evidence(customer, delivered)
    VerificationIssue.objects.filter(order=delivered).update(
        provider_decision_due_at=timezone.now() - timedelta(hours=1))
    with _capture(execute=True):
        check_provider_refunds()

    issue = VerificationIssue.objects.get(order=delivered)
    assert issue.status == IssueStatus.AWAITING_PROVIDER
    assert issue.provider_checked_at is not None


def test_a_declined_claim_is_rejected_with_the_providers_reply(user, customer, staff,
                                                               delivered, reviewing):
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    before = balance(user)

    reply = "The number received the code and worked as expected."
    response = act(staff, issue.reference, "provider-declined", reason=reply)
    assert response.status_code == 200, response.data

    issue.refresh_from_db()
    assert issue.status == IssueStatus.REJECTED
    assert issue.customer_reply == reply
    assert balance(user) == before
    seen = customer.get(f"/api/v1/orders/{delivered.reference}/").data["issue"]
    assert reply in seen["message"]


def test_staff_can_record_a_refund_the_provider_gave_through_support(
        user, customer, staff, delivered, reviewing):
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    before = balance(user)

    response = act(staff, issue.reference, "provider-refunded",
                   reason="TextVerified refunded the credits on ticket #4821")
    assert response.status_code == 200, response.data
    assert VerificationIssue.objects.get(pk=issue.pk).status == IssueStatus.REFUNDED
    assert balance(user) == before + delivered.price
    assert AdminAction.objects.filter(action="ISSUE_PROVIDER_REFUNDED").exists()


def test_staff_get_a_ticket_pack_and_the_screenshot_customers_do_not(
        customer, staff, delivered, reviewing):
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)

    detail = staff.get(f"/api/v1/admin/number-issues/{issue.reference}/").data
    pack = detail["ticket_pack"]
    assert pack["verification_id"] == delivered.provider_order_id
    assert "Screenshot attached" in pack["message"]
    assert delivered.phone_number not in pack["message"]  # never the full number

    (item,) = detail["evidence"]
    image = staff.get(f"/api/v1{item['url']}")
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image["X-Content-Type-Options"] == "nosniff"
    assert image.content == PNG
    assert customer.get(f"/api/v1{item['url']}").status_code == 403

    assert act(staff, issue.reference, "ticket-filed",
               reason="TextVerified ticket #4821").status_code == 200
    issue.refresh_from_db()
    assert issue.provider_ticket_reference == "TextVerified ticket #4821"
    assert issue.provider_ticket_filed_at is not None


def test_the_providers_report_window_is_minutes_not_hours(customer, delivered, reviewing):
    """TextVerified declined a claim filed six minutes after the code arrived."""
    from datetime import timedelta

    detail = customer.get(f"/api/v1/orders/{delivered.reference}/").data
    assert detail["report_needs_evidence"] is True
    assert detail["can_report"] is True
    ends = numbers.report_window_ends(Order.objects.get(pk=delivered.pk))
    assert ends - delivered.code_received_at == timedelta(minutes=5)

    Order.objects.filter(pk=delivered.pk).update(
        code_received_at=delivered.code_received_at - timedelta(minutes=6))
    late = customer.get(f"/api/v1/orders/{delivered.reference}/").data
    assert late["can_report"] is False
    response = report_with_evidence(customer, delivered)
    assert response.status_code == 409
    assert "5 minutes" in str(response.data)


def test_other_providers_keep_the_longer_window(customer, delivered):
    from datetime import timedelta

    detail = customer.get(f"/api/v1/orders/{delivered.reference}/").data
    assert detail["report_needs_evidence"] is False
    ends = numbers.report_window_ends(Order.objects.get(pk=delivered.pk))
    assert ends - delivered.code_received_at == timedelta(hours=72)


def test_a_long_pasted_provider_reply_is_accepted_whole(customer, staff, delivered, reviewing):
    """Production, 6 Oct: a pasted TextVerified reply was over 500 characters and
    the decline failed with a bare "information is not valid"."""
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    reply = ("Hello,\n\nWe don't provide refunds if the date on the ban is the date you "
             "received the verification.\n\n" + "More detail from support. " * 40
             + "\n\nHappy verifying!")
    assert 500 < len(reply) < 2000

    response = act(staff, issue.reference, "provider-declined", reason=reply)
    assert response.status_code == 200, response.data
    issue.refresh_from_db()
    assert issue.status == IssueStatus.REJECTED
    assert issue.customer_reply == reply.strip()
    seen = customer.get(f"/api/v1/orders/{delivered.reference}/").data["issue"]
    assert "Happy verifying!" in seen["message"]


def test_a_reply_over_the_limit_says_so(customer, staff, delivered, reviewing):
    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    response = act(staff, issue.reference, "provider-declined", reason="x" * 2001)
    assert response.status_code == 400
    assert "2000" in str(response.data)


def test_the_customer_is_told_only_what_was_actually_sent(customer, staff, delivered,
                                                          reviewing, monkeypatch):
    """9 Oct: TextVerified refused the API report once a code was delivered, but
    the customer was told their report and screenshot had been sent."""
    cls = verification_mock.MockVerificationProvider
    monkeypatch.setattr(cls, "report_number_issue",
                        lambda self, provider_order_id, reason: False)

    response = report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    assert issue.provider_report == "REFUSED"
    assert "reviewing your report" in response.data["message"]
    assert "sent your report" not in response.data["message"]

    # Once staff file the ticket, with the screenshot, it is true.
    assert act(staff, issue.reference, "ticket-filed",
               reason="TextVerified ticket #5001").status_code == 200
    seen = customer.get(f"/api/v1/orders/{delivered.reference}/").data
    message = (seen.get("issue") or {}).get("message", "")
    assert "sent your report and screenshot" in message, seen.get("issue")


def test_an_accepted_api_report_does_not_claim_the_screenshot_went_too(
        customer, delivered, reviewing):
    report_with_evidence(customer, delivered)
    assert VerificationIssue.objects.get(order=delivered).provider_report == "ACCEPTED"
    message = customer.get(f"/api/v1/orders/{delivered.reference}/").data["issue"]["message"]
    assert "sent your report to our number provider" in message
    assert "screenshot" not in message


GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24


def test_every_report_needs_a_screenshot_whatever_the_provider(customer, delivered):
    """Like TextVerified's own tickets: no screenshot, no report."""
    response = customer.post(f"/api/v1/orders/{delivered.reference}/report/", LINKED,
                             format="json")
    assert response.status_code == 400
    assert "phone's time" in response.data["error"]["message"]
    assert not VerificationIssue.objects.exists()


def test_report_screenshots_are_the_formats_textverified_takes(customer, delivered):
    webp = customer.post(f"/api/v1/orders/{delivered.reference}/report/",
                         {**LINKED, "evidence": [screenshot(WEBP, "x.webp")]}, format="multipart")
    assert webp.status_code == 400 and "JPG or GIF" in webp.data["error"]["message"]
    gif = customer.post(f"/api/v1/orders/{delivered.reference}/report/",
                        {**LINKED, "evidence": [screenshot(GIF, "x.gif")]}, format="multipart")
    assert gif.status_code == 201, gif.data


def test_a_declined_report_is_reversed_when_the_provider_refunds_after_all(
        user, customer, staff, delivered, reviewing):
    """9 Oct: TextVerified refunded a WhatsApp claim staff had already declined."""
    from django.core import mail

    report_with_evidence(customer, delivered)
    issue = VerificationIssue.objects.get(order=delivered)
    assert act(staff, issue.reference, "provider-declined",
               reason="Code was delivered.").status_code == 200
    before = balance(user)
    mail.outbox.clear()

    response = act(staff, issue.reference, "provider-refunded",
                   reason="TextVerified refunded the credits after review")
    assert response.status_code == 200, response.data
    issue.refresh_from_db()
    assert issue.status == IssueStatus.REFUNDED and issue.customer_reply == ""
    assert balance(user) == before + delivered.price
    assert AdminAction.objects.filter(action="ISSUE_DECISION_REVERSED").exists()
    assert any("approved" in m.subject.lower() or "approved" in m.body.lower()
               for m in mail.outbox), [m.subject for m in mail.outbox]

    # Once refunded it cannot be refunded again.
    assert act(staff, issue.reference, "provider-refunded",
               reason="again").status_code == 409
    assert balance(user) == before + delivered.price
