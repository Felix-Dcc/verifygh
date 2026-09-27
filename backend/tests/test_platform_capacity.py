"""The platform-wide concurrency cap.

Our supplier limits how many numbers one account may hold at once - OnlineSim's
standard limit is 40, confirmed by their support on 2026-09-27. Past that,
`getNum` starts refusing.

Without a cap of our own we would find their ceiling by hitting it: the wallet
debited, the order created, and only then an opaque upstream failure. The refund
path would cope, but the customer's experience is a purchase that appeared to
work and then unwound.

So the check belongs before the money moves, it counts every user's orders
rather than just the buyer's, and it says plainly that the limit is ours.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.orders.models import ACTIVE_ORDER_STATUSES, Order, OrderStatus
from apps.orders.services import check_purchase_eligibility
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

ORDERS = "/api/v1/orders/"
PASSWORD = "Correct-Horse-Battery-1"


@pytest.fixture
def buyer(db, funded_wallet):
    account = User.objects.create_user(
        email="capacity-buyer@example.com", password=PASSWORD, full_name="Capacity Buyer"
    )
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    funded_wallet(account)
    return account


def fill_platform(count: int, *, owner: User | None = None) -> list[Order]:
    """Put `count` orders in flight, spread across other users by default.

    Other users on purpose: the platform cap must count the whole queue, not
    the buyer's own orders, which the per-user cap already covers.
    """
    from apps.catalog.models import ProviderService

    offering = ProviderService.objects.select_related("service", "country").first()
    assert offering is not None, "the catalog fixture produced no offerings"

    made = []
    for index in range(count):
        holder = owner or User.objects.create_user(
            email=f"holder-{index}@example.com", password=PASSWORD
        )
        made.append(
            Order.objects.create(
                user=holder,
                reference=f"VG-CAP-{index:05d}",
                service=offering.service,
                country=offering.country,
                provider=offering.provider,
                status=OrderStatus.WAITING_FOR_CODE,
                price=Decimal("5.00"),
                provider_cost=Decimal("1.00"),
                currency="GHS",
                idempotency_key=f"capacity-fill-{index}",
            )
        )
    return made


# ---------------------------------------------------------------------------


def test_below_the_cap_a_purchase_is_allowed(catalog, buyer, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 5}
    fill_platform(4)

    # Does not raise.
    check_purchase_eligibility(buyer)


def test_at_the_cap_a_purchase_is_refused(catalog, buyer, settings):
    from apps.common.errors import ServiceUnavailable

    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 5}
    fill_platform(5)

    with pytest.raises(ServiceUnavailable) as raised:
        check_purchase_eligibility(buyer)

    assert raised.value.code == "PLATFORM_AT_CAPACITY"


def test_the_cap_counts_other_users_orders(catalog, buyer, settings):
    """The buyer has none of their own, yet the queue is full."""
    from apps.common.errors import ServiceUnavailable

    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 3}
    fill_platform(3)

    assert Order.objects.filter(user=buyer).count() == 0
    with pytest.raises(ServiceUnavailable):
        check_purchase_eligibility(buyer)


def test_finished_orders_do_not_count_against_capacity(catalog, buyer, settings):
    """A held number is released when the order finishes; the slot comes back."""
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 3}
    orders = fill_platform(3)
    for order in orders:
        Order.objects.filter(pk=order.pk).update(status=OrderStatus.COMPLETED)

    check_purchase_eligibility(buyer)


def test_a_zero_cap_disables_the_check(catalog, buyer, settings):
    """Right for the mock provider, where there is no upstream ceiling."""
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 0}
    fill_platform(25)

    check_purchase_eligibility(buyer)


def test_the_refusal_happens_before_any_money_moves(api, auth, catalog, buyer, settings):
    """The whole point: a full queue must not debit a wallet first."""
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 2}
    fill_platform(2)

    wallet = get_or_create_wallet(buyer)
    before = wallet.balance
    entries_before = wallet.ledger_entries.count()

    response = auth(buyer, PASSWORD).post(
        ORDERS, {"service": "instagram", "country": "US"}, format="json"
    )

    assert response.status_code == 503
    assert response.data["error"]["code"] == "PLATFORM_AT_CAPACITY"

    wallet.refresh_from_db()
    assert wallet.balance == before, "a refused purchase moved money"
    assert wallet.ledger_entries.count() == entries_before
    assert not Order.objects.filter(user=buyer).exists()


def test_the_message_does_not_blame_the_user(catalog, buyer, settings):
    """This limit is ours, not theirs - saying otherwise invites support tickets
    from people who have bought nothing all day."""
    from apps.common.errors import ServiceUnavailable

    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 1}
    fill_platform(1)

    with pytest.raises(ServiceUnavailable) as raised:
        check_purchase_eligibility(buyer)

    message = str(raised.value).lower()
    assert "we are at capacity" in message
    assert "you have" not in message
    assert "your" not in message


def test_the_eligibility_endpoint_reports_capacity(api, auth, catalog, buyer, settings):
    """The UI can then say "try again shortly" rather than offering a Buy button
    that is guaranteed to fail."""
    settings.VERIFYGH = {**settings.VERIFYGH, "MAX_PLATFORM_ACTIVE_ORDERS": 1}
    fill_platform(1)

    response = auth(buyer, PASSWORD).get(f"{ORDERS}eligibility/")

    assert response.status_code == 200
    assert response.data["eligible"] is False
    assert response.data["code"] == "PLATFORM_AT_CAPACITY"


def test_the_shipped_default_sits_below_the_suppliers_ceiling():
    """OnlineSim's standard limit is 40 numbers on hold.

    Ours must be lower, because our count and theirs drift: closing an operation
    is refused for 120 seconds when no SMS has arrived, so a number we consider
    released can still be held upstream.
    """
    from config.settings import base

    shipped = int(base.VERIFYGH["MAX_PLATFORM_ACTIVE_ORDERS"])
    supplier_ceiling = 40

    assert 0 < shipped < supplier_ceiling, (
        f"the platform cap ({shipped}) must leave headroom below the supplier's "
        f"{supplier_ceiling}-number ceiling"
    )
    assert shipped <= supplier_ceiling * 0.9, "too little headroom for drift"


def test_the_cap_leaves_room_for_several_users_at_their_personal_limit():
    """MAX_ACTIVE_ORDERS is per user. If the platform cap were only a small
    multiple of it, two busy users would starve everybody else."""
    from config.settings import base

    per_user = int(base.VERIFYGH["MAX_ACTIVE_ORDERS"])
    platform = int(base.VERIFYGH["MAX_PLATFORM_ACTIVE_ORDERS"])

    assert platform >= per_user * 5, (
        f"a platform cap of {platform} with a per-user cap of {per_user} lets "
        f"{platform // per_user} users block the marketplace"
    )
