"""Reported numbers: history, the flagged-number screen, reports and remedies.

Reproduces the TikTok case - a code arrives, the customer uses it, and the
service asks for an existing password - and follows it through every outcome
staff can choose, checking the ledger and the audit trail at each step.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.constants import Role
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
    return client.post(f"/api/v1/orders/{order.reference}/report/", body, format="json")


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
