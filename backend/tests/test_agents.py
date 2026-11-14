"""Agents: commission on referred customers' purchases, and cash payouts.

Ama is the agent, Kwame the customer she referred. Commission follows the cash
Kwame pays for delivered numbers, is frozen at the rate of the day, goes away
when a sale is refunded, and is paid down by payouts staff record.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.catalog.models import Provider
from apps.orders.models import Order, OrderStatus
from apps.orders.services import poll_order
from apps.referrals import agents
from apps.referrals.models import (
    Agent,
    AgentCommission,
    AgentPayout,
    CommissionStatus,
    Referral,
    ReferralProgram,
    ReferralRiskFlag,
    ReferralStatus,
    RiskKind,
)
from apps.referrals.services import attach_referral, code_for, evaluate
from apps.rentals.models import Rental, RentalStatus
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

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
def staff(admin_user):
    return sign_in(admin_user, "Correct-Horse-Battery-3")


@pytest.fixture
def customer(user, other_user, catalog, funded_wallet):
    """Kwame, referred by Ama, with cash in his wallet."""
    Referral.objects.create(referrer=other_user, referred_user=user, code="AMA12345")
    funded_wallet(user, "200.00")
    return sign_in(user, "Correct-Horse-Battery-1")


@pytest.fixture
def agent(staff, other_user) -> Agent:
    response = staff.post("/api/v1/admin/agents/", {"email": other_user.email}, format="json")
    assert response.status_code == 201, response.data
    return Agent.objects.get(user=other_user)


def buy(client) -> Order:
    """A delivered order, paid in cash."""
    verification_mock.force_scenario("HAPPY")
    with _capture(execute=True):
        response = client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                               format="json")
    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])
    verification_mock.fast_forward(order.provider_order_id, 30)
    order = poll_order(order)
    assert order.status == OrderStatus.CODE_RECEIVED
    assert order.cash_amount == order.price > 0
    return order


def mine(other_user) -> dict:
    return sign_in(other_user, "Correct-Horse-Battery-2").get("/api/v1/referrals/agent/").data


def five_percent(amount) -> Decimal:
    return (Decimal(amount) * Decimal("0.05")).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Earning
# ---------------------------------------------------------------------------


def test_a_referred_customers_purchase_earns_the_agent_five_percent(
        agent, customer, other_user):
    order = buy(customer)

    page = mine(other_user)
    assert page["is_agent"] is True
    assert page["commission_percent"] == "5.00"
    assert page["earned"] == page["balance"] == str(five_percent(order.cash_amount))
    assert page["sales"] == 1 and page["customers"] == 1
    row = page["commissions"][0]
    assert row["reference"] == order.reference
    assert row["customer"] == "k***@example.com"  # never the customer's address

    # Reading again never pays twice.
    assert mine(other_user)["earned"] == page["earned"]
    assert AgentCommission.objects.count() == 1


def test_a_rental_earns_commission_too(agent, customer, user, other_user):
    Rental.objects.create(
        reference="RNT-TEST1", user=user, provider=Provider.objects.first(),
        provider_service_name="whatsapp", days=7, price=Decimal("60.00"),
        cash_amount=Decimal("60.00"), status=RentalStatus.ACTIVE, idempotency_key="r1",
    )
    assert mine(other_user)["earned"] == "3.00"


def test_a_refunded_sale_takes_its_commission_back(agent, customer, other_user):
    order = buy(customer)
    assert Decimal(mine(other_user)["balance"]) > 0

    Order.objects.filter(pk=order.pk).update(refunded_amount=order.price)

    page = mine(other_user)
    assert page["earned"] == page["balance"] == "0.00"
    assert page["commissions"][0]["status"] == CommissionStatus.REVERSED


def test_nothing_is_earned_on_sales_that_do_not_qualify(
        staff, customer, user, other_user, funded_wallet):
    before = buy(customer)  # bought before Ama was an agent
    staff.post("/api/v1/admin/agents/", {"email": other_user.email}, format="json")
    assert mine(other_user)["earned"] == "0.00"

    # A referral staff rejected earns nothing.
    Referral.objects.update(status=ReferralStatus.REJECTED)
    buy(customer)
    assert mine(other_user)["earned"] == "0.00"
    Referral.objects.update(status=ReferralStatus.PENDING)

    # Nor does the agent's own second account.
    flag = ReferralRiskFlag.objects.create(referral=Referral.objects.get(),
                                           kind=RiskKind.SHARED_DEVICE, blocking=True)
    assert mine(other_user)["earned"] == "0.00"
    flag.delete()

    # Promotional credit is not cash.
    Order.objects.exclude(pk=before.pk).update(cash_amount=Decimal("0.00"))
    assert mine(other_user)["earned"] == "0.00"


def test_a_paused_agent_earns_nothing_until_resumed(agent, staff, customer, other_user):
    url = f"/api/v1/admin/agents/{agent.pk}/"
    assert staff.patch(url, {"is_active": False}, format="json").status_code == 200
    buy(customer)
    assert mine(other_user)["earned"] == "0.00"

    # Resuming does not pay for what was bought while paused.
    assert staff.patch(url, {"is_active": True}, format="json").status_code == 200
    assert mine(other_user)["earned"] == "0.00"
    order = buy(customer)
    assert mine(other_user)["earned"] == str(five_percent(order.cash_amount))


def test_changing_the_rate_leaves_what_was_already_earned(agent, staff, customer, other_user):
    first = buy(customer)
    response = staff.patch(f"/api/v1/admin/agents/{agent.pk}/",
                           {"commission_percent": "10.00"}, format="json")
    assert response.status_code == 200, response.data
    second = buy(customer)

    expected = five_percent(first.cash_amount) + (second.cash_amount * Decimal("0.10")).quantize(
        Decimal("0.01"))
    assert mine(other_user)["earned"] == str(expected)
    assert staff.patch(f"/api/v1/admin/agents/{agent.pk}/",
                       {"commission_percent": "60"}, format="json").status_code == 400


# ---------------------------------------------------------------------------
# Paying out
# ---------------------------------------------------------------------------


def test_a_payout_reduces_what_is_owed_and_cannot_exceed_it(agent, staff, customer, other_user):
    order = buy(customer)
    owed = five_percent(order.cash_amount)
    url = f"/api/v1/admin/agents/{agent.pk}/payouts/"

    too_much = staff.post(url, {"amount": str(owed + Decimal("0.01")), "reference": "MOMO-1"},
                          format="json")
    assert too_much.status_code == 400
    assert staff.post(url, {"amount": str(owed), "reference": ""},
                      format="json").status_code == 400

    paid = staff.post(url, {"amount": str(owed), "reference": "MOMO-1"}, format="json")
    assert paid.status_code == 201, paid.data
    assert paid.data["paid"] == str(owed) and paid.data["balance"] == "0.00"
    assert AgentPayout.objects.get().reference == "MOMO-1"
    assert AdminAction.objects.filter(action="AGENT_PAYOUT").count() == 1

    page = mine(other_user)
    assert page["balance"] == "0.00" and page["payouts"][0]["amount"] == str(owed)

    # A refund after the payout leaves the agent owing it back.
    Order.objects.filter(pk=order.pk).update(refunded_amount=order.price)
    assert mine(other_user)["balance"] == str(-owed)


# ---------------------------------------------------------------------------
# Who may do what
# ---------------------------------------------------------------------------


def test_only_staff_with_the_right_permission_manage_agents(
        agent, customer, user, support_user):
    assert customer.get("/api/v1/admin/agents/").status_code == 403
    assert customer.get("/api/v1/referrals/agent/").data == {"is_agent": False}

    support = sign_in(support_user, "Correct-Horse-Battery-4")
    assert support.get("/api/v1/admin/agents/").status_code == 200
    assert support.post("/api/v1/admin/agents/", {"email": user.email},
                        format="json").status_code == 403
    assert support.patch(f"/api/v1/admin/agents/{agent.pk}/", {"is_active": False},
                         format="json").status_code == 403
    assert support.post(f"/api/v1/admin/agents/{agent.pk}/payouts/",
                        {"amount": "1.00", "reference": "X"}, format="json").status_code == 403


def test_registering_needs_an_existing_account_and_happens_once(staff, agent, other_user):
    assert staff.post("/api/v1/admin/agents/", {"email": "nobody@example.com"},
                      format="json").status_code == 404
    assert staff.post("/api/v1/admin/agents/", {"email": other_user.email},
                      format="json").status_code == 409

    listing = staff.get("/api/v1/admin/agents/").data
    assert listing["default_percent"] == "5.00"
    assert [row["email"] for row in listing["results"]] == [other_user.email]
    assert agent.active_since <= timezone.now()
    assert agents.totals(agent)["balance"] == "0.00"


def test_an_agents_link_still_counts_while_the_referral_programme_is_off(
        agent, user, other_user, admin_user):
    program = ReferralProgram.load()
    program.is_enabled = False
    program.save()

    # Anyone else's code is ignored while the programme is off...
    assert attach_referral(new_user=user, raw_code=code_for(admin_user).code) is None
    # ...an agent's is their channel.
    referral = attach_referral(new_user=user, raw_code=code_for(other_user).code)
    assert referral is not None and referral.referrer == other_user
    assert evaluate(referral).status == ReferralStatus.PENDING  # and no bonus is paid
