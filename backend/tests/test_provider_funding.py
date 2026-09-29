"""Provider funding: the prepaid OnlineSim balance, guarded, watched and accounted for.

OnlineSim is prepaid only and has no funding API (docs/PROVIDER-FUNDING.md).
These tests pin down what software can do about it: never charge a customer
for a purchase the provider balance visibly cannot cover, tell staff the real
reason while customers see "temporarily unavailable", fail over only to
authorised providers, keep customer money and our money apart, and never
pretend a provider can be funded through an API.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings as django_settings
from django.core import mail
from django.utils import timezone

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.catalog.models import Provider, ProviderService
from apps.common.errors import ProviderError
from apps.funding import services as funding
from apps.funding.models import (
    AlertKind,
    BalanceStatus,
    ProviderAccount,
    ProviderAlert,
    ProviderTopUp,
)
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderEvent, OrderStatus
from apps.verification import mock as verification_mock
from apps.verification import registry
from apps.verification.mock import MockVerificationProvider
from apps.verification.onlinesim import OnlineSimProvider
from apps.wallet.models import WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
ADMIN_PASSWORD = "Correct-Horse-Battery-3"
FUNDING = "/api/v1/admin/funding/"


@pytest.fixture(autouse=True)
def _commit_hooks(django_capture_on_commit_callbacks):
    """Alerts are delivered, and orders fulfilled, after commit. Run those hooks."""
    global run
    run = django_capture_on_commit_callbacks
    yield


def committed(fn, *args, **kwargs):
    with run(execute=True):
        return fn(*args, **kwargs)


def buy(client, service="instagram", country="US"):
    with run(execute=True):
        return client.post("/api/v1/orders/", {"service": service, "country": country},
                           format="json")


@pytest.fixture
def mock_provider(catalog):
    return Provider.objects.get(adapter_key="mock")


@pytest.fixture
def instagram_us(mock_provider):
    return ProviderService.objects.select_related("provider", "service", "country").get(
        provider=mock_provider, service__slug="instagram", country__code="US")


@pytest.fixture
def plain_admin(db):
    return User.objects.create_user(email="ops-admin@verifygh.local", password=PASSWORD,
                                    role=Role.ADMIN, is_email_verified=True)


def set_balance(amount, provider: Provider, key="mock"):
    verification_mock.set_balance(amount, key=key)
    return committed(funding.sync_balance, provider)


# ---------------------------------------------------------------------------
# The provider interface
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self.content = b"x"
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None, headers=None, timeout=None):
        return self.routes[url.split("onlinesim.io", 1)[-1]]


@pytest.fixture
def onlinesim(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "onlinesim": {"api_key": "test-key", "base_url": "https://onlinesim.io",
                      "currency": "USD"},
    }
    return OnlineSimProvider()


def test_onlinesim_balance_separates_spendable_from_frozen(onlinesim):
    onlinesim._session = _Session({onlinesim.PATH_BALANCE: _Resp(
        {"response": "1", "balance": "5.051", "zbalance": "0.25"})})

    reading = onlinesim.get_balance()

    assert reading.available == Decimal("5.051")
    assert reading.frozen == Decimal("0.25")
    assert reading.currency == "USD"


def test_an_empty_balance_error_is_labelled_for_staff_but_generic_for_customers(onlinesim):
    onlinesim._session = _Session({onlinesim.PATH_BALANCE: _Resp(
        {"response": "WARNING_LOW_BALANCE"})})

    with pytest.raises(ProviderError) as raised:
        onlinesim._get(onlinesim.PATH_BALANCE)

    assert raised.value.provider_code == "WARNING_LOW_BALANCE"
    assert raised.value.operational is True
    assert "balance" not in raised.value.message.lower()


def test_no_provider_claims_it_can_be_funded_through_its_api(onlinesim):
    """OnlineSim documents no funding endpoint. Nothing may pretend otherwise."""
    for adapter in (onlinesim, MockVerificationProvider(), registry.get_provider("mock")):
        assert adapter.supports_account_funding is False
        with pytest.raises(NotImplementedError):
            adapter.fund_account(Decimal("10"), "USD", "ref")

    paths = [name for name in dir(OnlineSimProvider) if name.startswith("PATH_")]
    for name in paths:
        value = getattr(OnlineSimProvider, name).lower()
        assert not any(word in value for word in ("fund", "topup", "top_up", "deposit", "pay"))


# ---------------------------------------------------------------------------
# Reading and grading the balance
# ---------------------------------------------------------------------------


def test_a_healthy_balance_needs_no_top_up(mock_provider):
    account = set_balance("50", mock_provider)

    assert account.status == BalanceStatus.HEALTHY
    assert account.available == Decimal("50.0000")
    assert funding.recommended_top_up(account) == Decimal("0")
    assert not ProviderAlert.objects.exists()


def test_recommended_top_up_returns_the_account_to_target(mock_provider):
    account = set_balance("5.051", mock_provider)
    assert account.status == BalanceStatus.HEALTHY  # just above the $5 minimum
    # Target 20 - 5.051 = 14.949, rounded up to a whole dollar.
    assert funding.recommended_top_up(account) == Decimal("15")

    account = set_balance("4.051", mock_provider)
    assert account.status == BalanceStatus.LOW
    assert funding.recommended_top_up(account) == Decimal("16")


def test_a_low_balance_alerts_the_people_who_can_fix_it(mock_provider, admin_user,
                                                        support_user, plain_admin, user):
    set_balance("50", mock_provider)
    set_balance("4", mock_provider)

    alert = ProviderAlert.objects.get(kind=AlertKind.LOW_BALANCE)
    assert "Recommended top-up: USD 16.00" in alert.message
    assert "no API" in alert.message

    told = set(Notification.objects.filter(event="PROVIDER_LOW_BALANCE")
               .values_list("user__email", "channel"))
    assert told == {(admin_user.email, "IN_APP"), (admin_user.email, "EMAIL")}
    assert any(admin_user.email in message.to for message in mail.outbox)
    # Customers, support and plain admins are not the audience.
    assert not Notification.objects.filter(
        user__in=[user, support_user, plain_admin], event__startswith="PROVIDER_").exists()


def test_critical_alerts_once_on_the_way_down_not_every_sync(mock_provider, admin_user):
    set_balance("50", mock_provider)
    set_balance("1", mock_provider)
    set_balance("0.5", mock_provider)
    set_balance("0.4", mock_provider)

    assert ProviderAlert.objects.filter(kind=AlertKind.CRITICAL_BALANCE).count() == 1
    assert ProviderAccount.objects.get(provider=mock_provider).status == BalanceStatus.CRITICAL


def test_recovery_is_announced_in_app_only(mock_provider, admin_user):
    set_balance("1", mock_provider)
    mail.outbox.clear()
    set_balance("40", mock_provider)

    assert ProviderAlert.objects.filter(kind=AlertKind.BALANCE_RECOVERED).count() == 1
    channels = set(Notification.objects.filter(event="PROVIDER_BALANCE_RECOVERED")
                   .values_list("channel", flat=True))
    assert channels == {"IN_APP"}
    assert not mail.outbox


def test_sync_failures_keep_the_last_reading_and_alert_after_a_streak(mock_provider,
                                                                      admin_user, settings):
    set_balance("30", mock_provider)
    verification_mock.set_balance("error")

    for _ in range(2):
        account = committed(funding.sync_balance, mock_provider)
    assert account.available == Decimal("30.0000")
    assert account.consecutive_sync_failures == 2
    assert not ProviderAlert.objects.filter(kind=AlertKind.SYNC_FAILED).exists()

    account = committed(funding.sync_balance, mock_provider)
    assert account.consecutive_sync_failures == 3
    assert ProviderAlert.objects.filter(kind=AlertKind.SYNC_FAILED).count() == 1

    set_balance("30", mock_provider)
    assert ProviderAccount.objects.get(provider=mock_provider).consecutive_sync_failures == 0


# ---------------------------------------------------------------------------
# The guard: refuse before charging
# ---------------------------------------------------------------------------


@pytest.fixture
def buyer(user, funded_wallet):
    funded_wallet(user, "200.00")
    return user


def test_an_unfunded_provider_refuses_before_any_money_moves(api, auth, buyer, instagram_us,
                                                             admin_user):
    verification_mock.force_scenario("HAPPY")
    set_balance("0.10", instagram_us.provider)
    wallet = get_or_create_wallet(buyer)
    entries = wallet.ledger_entries.count()

    response = buy(auth(buyer))

    assert response.status_code == 503
    assert response.data["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
    message = response.data["error"]["message"].lower()
    assert "temporarily unavailable" in message
    for leak in ("balance", "onlinesim", "mock", "provider", "fund"):
        assert leak not in message

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert wallet.ledger_entries.count() == entries
    assert not Order.objects.filter(user=buyer).exists()

    # Staff get the real reason.
    alert = ProviderAlert.objects.get(kind=AlertKind.PURCHASE_BLOCKED)
    assert "Instagram (US)" in alert.message and "USD 0.10" in alert.message
    assert alert.metadata["service"] == "instagram"


def test_a_funded_provider_sells_normally(api, auth, buyer, instagram_us):
    verification_mock.force_scenario("HAPPY")
    set_balance("100", instagram_us.provider)

    response = buy(auth(buyer))

    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])
    assert order.status == OrderStatus.WAITING_FOR_CODE


def test_a_stale_low_reading_is_rechecked_live_before_refusing(api, auth, buyer, instagram_us):
    """Staff topped up a minute ago; the customer must not be turned away."""
    verification_mock.force_scenario("HAPPY")
    set_balance("0.10", instagram_us.provider)
    ProviderAccount.objects.filter(provider=instagram_us.provider).update(
        last_sync_attempt_at=timezone.now() - timedelta(minutes=5))
    verification_mock.set_balance("100")

    response = buy(auth(buyer))

    assert response.status_code == 201, response.data
    assert ProviderAccount.objects.get(
        provider=instagram_us.provider).available == Decimal("100.0000")


def test_an_unknown_balance_does_not_block_sales(api, auth, buyer, instagram_us):
    """Never read = unknown. The provider stays the judge; the refund path is intact."""
    verification_mock.force_scenario("HAPPY")
    assert not ProviderAccount.objects.exists()

    assert buy(auth(buyer)).status_code == 201


def test_with_the_guard_off_a_provider_refusal_is_still_refunded_and_reported(
        api, auth, buyer, instagram_us, admin_user, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "PROVIDER_FUNDING_GUARD": False}
    verification_mock.force_scenario("HAPPY")
    set_balance("0.10", instagram_us.provider)

    response = buy(auth(buyer))

    order = Order.objects.get(reference=response.data["reference"])
    assert order.status == OrderStatus.REFUNDED
    wallet = get_or_create_wallet(buyer)
    assert wallet.balance == Decimal("200.00")
    assert verify_wallet_integrity(wallet)["ok"] is True

    alert = ProviderAlert.objects.get(kind=AlertKind.PROVIDER_REFUSED)
    assert "WARNING_LOW_BALANCE" in alert.message


def test_a_free_replacement_is_refused_with_the_real_reason_for_staff(instagram_us):
    from apps.orders.services import resolve_offering

    set_balance("0.10", instagram_us.provider)
    check = funding.check_funding(resolve_offering("instagram", "US"))

    assert check.ok is False
    assert "cannot cover Instagram (US)" in check.reason


# ---------------------------------------------------------------------------
# Failover: only to authorised providers, never at a higher price
# ---------------------------------------------------------------------------


class SecondMock(MockVerificationProvider):
    key = "mock2"
    display_name = "Second mock"


@pytest.fixture
def second_provider(catalog):
    from apps.catalog.services import sync_catalog

    registry.register(SecondMock)
    try:
        sync_catalog("mock2")
        provider = Provider.objects.get(adapter_key="mock2")
        Provider.objects.filter(pk=provider.pk).update(name="Second", priority=500)
        provider.refresh_from_db()
        yield provider
    finally:
        registry._REGISTRY.pop("mock2", None)


def test_an_unfunded_primary_fails_over_to_a_funded_authorised_provider(
        api, auth, buyer, instagram_us, second_provider):
    verification_mock.force_scenario("HAPPY")
    set_balance("0.10", instagram_us.provider)
    set_balance("100", second_provider, key="mock2")

    response = buy(auth(buyer))

    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])
    assert order.provider == second_provider
    assert order.status == OrderStatus.WAITING_FOR_CODE


def test_failover_never_charges_more_than_the_price_shown(api, auth, buyer, instagram_us,
                                                          second_provider):
    from apps.pricing.models import MarkupType, PricingRule

    PricingRule.objects.create(name="Second is dearer", provider=second_provider,
                               markup_type=MarkupType.PERCENTAGE,
                               markup_percent=Decimal("300.00"), priority=1)
    from apps.pricing.history import refresh_offering_prices

    refresh_offering_prices(source="PRICING_RULE", reason="test", actor=None)
    verification_mock.force_scenario("HAPPY")
    set_balance("0.10", instagram_us.provider)
    set_balance("100", second_provider, key="mock2")

    response = buy(auth(buyer))

    assert response.status_code == 503
    assert response.data["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
    assert not Order.objects.filter(user=buyer).exists()


def test_a_provider_without_a_registered_adapter_is_never_used(api, auth, buyer, instagram_us):
    """TextVerified refused resale. Even a stray enabled row must not be bought from."""
    stray = Provider.objects.create(adapter_key="textverified", name="TextVerified",
                                    is_enabled=True, priority=1)
    ProviderService.objects.create(
        provider=stray, service=instagram_us.service, country=instagram_us.country,
        provider_service_code="instagram", cost_amount=Decimal("0.10"), is_enabled=True,
        is_available=True,
    )
    verification_mock.force_scenario("HAPPY")
    set_balance("100", instagram_us.provider)

    response = buy(auth(buyer))

    assert response.status_code == 201, response.data
    assert Order.objects.get(reference=response.data["reference"]).provider.adapter_key == "mock"


# ---------------------------------------------------------------------------
# Top-ups: bookkeeping only, never customer money
# ---------------------------------------------------------------------------


def test_recording_a_top_up_moves_no_customer_money_and_confirms_itself(
        api, auth, admin_user, user, funded_wallet, mock_provider):
    funded_wallet(user, "80.00")
    set_balance("2", mock_provider)
    entries = WalletLedgerEntry.objects.count()
    verification_mock.set_balance("27")  # the payment on the provider website landed

    client = auth(admin_user, ADMIN_PASSWORD)
    with run(execute=True):
        response = client.post(f"{FUNDING}mock/top-ups/", {
            "amount": "25", "currency": "USD", "method": "CRYPTO",
            "external_reference": "OS-INV-8812", "paid_ghs": "312.50",
            "note": "Weekly reserve top-up",
        }, format="json")

    assert response.status_code == 201, response.data
    top_up = ProviderTopUp.objects.get()
    assert top_up.balance_before == Decimal("2.0000")
    assert top_up.confirmed_at is not None
    assert top_up.confirmed_balance == Decimal("27.0000")
    assert WalletLedgerEntry.objects.count() == entries
    assert get_or_create_wallet(user).balance == Decimal("80.00")
    assert AdminAction.objects.filter(action="PROVIDER_TOP_UP_RECORDED").count() == 1


def test_only_provider_managers_can_record_top_ups_or_change_levels(api, auth, plain_admin,
                                                                    mock_provider):
    client = auth(plain_admin)

    assert client.get(FUNDING).status_code == 200
    assert client.post(f"{FUNDING}mock/top-ups/", {"amount": "5", "method": "CARD"},
                       format="json").status_code == 403
    assert client.patch(f"{FUNDING}mock/", {"minimum_balance": "1", "reason": "testing"},
                        format="json").status_code == 403


def test_customers_and_support_cannot_see_funding(api, auth, user, support_user, catalog):
    assert auth(user).get(FUNDING).status_code == 403
    api.credentials()
    assert auth(support_user, "Correct-Horse-Battery-4").get(FUNDING).status_code == 403


def test_a_card_number_is_never_stored(admin_user, mock_provider):
    account = funding.account_for(mock_provider)

    with pytest.raises(Exception) as raised:
        funding.record_top_up(account, actor=admin_user, data={
            "amount": "10", "method": "CARD", "external_reference": "4111 1111 1111 1111"})

    assert "card number" in str(raised.value)
    assert not ProviderTopUp.objects.exists()


def test_a_top_up_that_never_arrives_is_flagged(admin_user, mock_provider):
    set_balance("3", mock_provider)
    top_up = committed(funding.record_top_up, funding.account_for(mock_provider),
                       actor=admin_user,
                       data={"amount": "10", "method": "BANK_TRANSFER"})
    assert top_up.confirmed_at is None
    ProviderTopUp.objects.filter(pk=top_up.pk).update(
        created_at=timezone.now() - timedelta(hours=25))

    committed(funding.sync_all)

    assert ProviderAlert.objects.filter(kind=AlertKind.TOP_UP_NOT_REFLECTED).count() == 1
    committed(funding.sync_all)
    assert ProviderAlert.objects.filter(kind=AlertKind.TOP_UP_NOT_REFLECTED).count() == 1


def test_reserve_levels_are_validated_and_audited(api, auth, admin_user, mock_provider):
    set_balance("6", mock_provider)
    client = auth(admin_user, ADMIN_PASSWORD)

    bad = client.patch(f"{FUNDING}mock/", {"critical_balance": "9", "minimum_balance": "5",
                                          "reason": "try it"}, format="json")
    assert bad.status_code == 400
    unexplained = client.patch(f"{FUNDING}mock/", {"minimum_balance": "8"}, format="json")
    assert unexplained.status_code == 400

    with run(execute=True):
        ok = client.patch(f"{FUNDING}mock/", {"minimum_balance": "8", "target_balance": "40",
                                             "reason": "Busier week ahead"}, format="json")
    assert ok.status_code == 200, ok.data
    assert ok.data["status"] == BalanceStatus.LOW
    assert ok.data["recommended_top_up"] == "34.0000"
    assert AdminAction.objects.filter(action="PROVIDER_FUNDING_SETTINGS").count() == 1


# ---------------------------------------------------------------------------
# Scheduled checks
# ---------------------------------------------------------------------------


def _order(provider, service, country, index, **fields):
    holder = User.objects.create_user(email=f"funding-{index}@example.com", password=PASSWORD)
    return Order.objects.create(
        user=holder, reference=f"VG-FUND-{index:05d}", service=service, country=country,
        provider=provider, price=Decimal("5.00"), provider_cost=Decimal("0.30"),
        exchange_rate=Decimal("12.00"), currency="GHS", idempotency_key=f"funding-{index}",
        **fields,
    )


def test_an_account_close_to_inactivity_deletion_is_flagged(instagram_us, admin_user):
    _order(instagram_us.provider, instagram_us.service, instagram_us.country, 1,
           status=OrderStatus.COMPLETED,
           code_received_at=timezone.now() - timedelta(days=22))
    set_balance("30", instagram_us.provider)

    committed(funding.sync_all)

    alert = ProviderAlert.objects.get(kind=AlertKind.INACTIVITY)
    assert "22 days" in alert.message and "USD 30.00" in alert.message


def test_a_spike_in_failed_orders_is_flagged(instagram_us, admin_user):
    for index in range(5):
        order = _order(instagram_us.provider, instagram_us.service, instagram_us.country,
                       index + 10, status=OrderStatus.FAILED)
        OrderEvent.objects.create(order=order, status=OrderStatus.FAILED, label="Failed")

    committed(funding.sync_all)

    assert ProviderAlert.objects.filter(kind=AlertKind.FAILURE_SPIKE).count() == 1


def test_the_balance_sync_is_scheduled():
    from config.celery import app

    tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert "apps.funding.tasks.sync_provider_balances" in tasks


# ---------------------------------------------------------------------------
# Cash flow: customer money is not profit
# ---------------------------------------------------------------------------


def test_cash_flow_keeps_customer_money_apart_from_profit(api, auth, admin_user, user,
                                                          funded_wallet, instagram_us):
    funded_wallet(user, "150.00")
    _order(instagram_us.provider, instagram_us.service, instagram_us.country, 40,
           status=OrderStatus.COMPLETED, code_received_at=timezone.now())
    set_balance("10", instagram_us.provider)

    data = auth(admin_user, ADMIN_PASSWORD).get(FUNDING).data
    flow = data["cash_flow"]

    assert flow["customer_funds"]["wallet_cash"] == "150.00"
    # One delivered order: GHS 5.00 price, USD 0.30 x 12.00 = GHS 3.60 cost.
    assert flow["earnings_30d"] == {"revenue": "5.00", "provider_cost": "3.60",
                                    "gross_profit": "1.40"}
    assert "not VerifyGH profit" in flow["wallet_is_not_profit"]
    # A deposit is not revenue.
    assert flow["earnings_all_time"]["revenue"] == "5.00"

    account = data["accounts"][0]
    assert account["adapter_key"] == "mock"
    assert account["supports_account_funding"] is False
    assert account["balance"] == "10.0000"
    assert "no funding API" in account["funding_instructions"]
    assert django_settings.VERIFYGH["PROVIDER_FUNDING_GUARD"] is account["guard_enabled"]


def test_no_shortfall_is_claimed_while_a_balance_is_unread(user, funded_wallet, instagram_us):
    """Unread is not zero. Reporting a shortfall from it would be invented."""
    funded_wallet(user, "150.00")
    _order(instagram_us.provider, instagram_us.service, instagram_us.country, 50,
           status=OrderStatus.COMPLETED, code_received_at=timezone.now())
    # No account row at all yet (the first sync has not run) ...
    flow = funding.cash_flow()
    assert flow["provider_balance_unread"] == ["Mock"]
    assert flow["estimated_shortfall_ghs"] is None

    # ... and a row whose balance has never been read.
    funding.account_for(instagram_us.provider)
    flow = funding.cash_flow()
    assert flow["provider_balance_unread"] == ["Mock"]
    assert flow["estimated_shortfall_ghs"] is None
    assert flow["estimated_cost_to_serve_wallets_ghs"] is not None
