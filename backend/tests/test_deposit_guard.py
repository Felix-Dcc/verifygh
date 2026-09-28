"""Deposits are refused while there is nothing to buy.

The failure this prevents is quiet and bad. Deposits and the catalogue are
independent: money can be taken while `VERIFICATION_PROVIDER` is inert, the
exchange rate is missing, or the last offering has sold out. Nothing errors -
the wallet is credited exactly as designed.

But that money cannot be spent, because there is nothing to buy, and it cannot
be withdrawn, because promotional and cash balances are not withdrawable. From
the customer's side that is indistinguishable from having been robbed, and they
would be right to be angry.

So the till closes when the shelves are empty.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.models import User
from apps.catalog.models import ProviderService
from apps.catalog.services import marketplace_readiness
from apps.common.errors import ServiceUnavailable
from apps.payments.models import Payment
from apps.payments.services import deposits_blocked_reason, initiate_deposit
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db

DEPOSIT = "/api/v1/payments/deposit/"
OPTIONS = "/api/v1/payments/options/"
PASSWORD = "Correct-Horse-Battery-1"


@pytest.fixture(autouse=True)
def _guard_enabled(settings):
    """The suite disables this guard so payment tests need no catalogue.

    This module is the one that actually exercises it, so it turns it back on
    for every test here.
    """
    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": True}


@pytest.fixture
def depositor(db):
    account = User.objects.create_user(
        email="depositor@example.com", password=PASSWORD, full_name="Depositor",
        phone="+233241234599",
    )
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


def deposit(client, amount="20.00"):
    return client.post(
        DEPOSIT,
        {"amount": amount, "phone": "0241234599", "network": "MTN"},
        format="json",
    )


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_a_stocked_catalogue_allows_deposits(catalog, depositor):
    assert marketplace_readiness()["ready"] is True
    assert deposits_blocked_reason() == ""

    payment = initiate_deposit(
        user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
    )
    assert payment.pk is not None


def test_an_empty_catalogue_blocks_deposits(catalog, depositor):
    ProviderService.objects.update(is_available=False)

    assert marketplace_readiness()["ready"] is False
    with pytest.raises(ServiceUnavailable) as raised:
        initiate_deposit(
            user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
        )

    assert raised.value.code == "DEPOSITS_PAUSED"


def test_a_missing_exchange_rate_blocks_deposits(catalog, depositor):
    """Without a rate nothing can be priced in cedis, so nothing can be bought."""
    from apps.pricing.models import ExchangeRate

    ExchangeRate.objects.all().delete()

    assert marketplace_readiness()["ready"] is False
    with pytest.raises(ServiceUnavailable):
        initiate_deposit(
            user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
        )


def test_no_payment_row_is_created_when_deposits_are_paused(catalog, depositor):
    """A refused deposit must leave nothing behind to reconcile or expire."""
    ProviderService.objects.update(is_available=False)

    before = Payment.objects.count()
    with pytest.raises(ServiceUnavailable):
        initiate_deposit(
            user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
        )

    assert Payment.objects.count() == before


def test_the_guard_runs_before_the_amount_is_validated(catalog, depositor):
    """An empty marketplace makes the amount moot.

    Complaining about the amount first would send someone away to fix a number
    that was never the problem, and they would come back and fail again.
    """
    ProviderService.objects.update(is_available=False)

    with pytest.raises(ServiceUnavailable) as raised:
        # Far below MIN_DEPOSIT: the amount check would reject this too.
        initiate_deposit(
            user=depositor, amount=Decimal("0.01"), phone="+233241234599", network="MTN"
        )

    assert raised.value.code == "DEPOSITS_PAUSED"


def test_the_message_reassures_about_the_existing_balance(catalog, depositor):
    """Someone told "top-ups are paused" will immediately fear for their money."""
    ProviderService.objects.update(is_available=False)

    reason = deposits_blocked_reason()

    assert "balance is safe" in reason.lower()


def test_the_message_does_not_expose_which_precondition_failed(catalog, depositor):
    """A customer can act on none of it, and it advertises how we are wired."""
    from apps.pricing.models import ExchangeRate

    ExchangeRate.objects.all().delete()

    reason = deposits_blocked_reason().lower()

    assert "exchange rate" not in reason
    assert "provider" not in reason
    assert "catalog" not in reason


def test_the_guard_can_be_switched_off_for_staging(catalog, depositor, settings):
    """A stack deliberately exercising deposits on an empty catalogue."""
    settings.VERIFYGH = {**settings.VERIFYGH, "REQUIRE_CATALOG_FOR_DEPOSIT": False}
    ProviderService.objects.update(is_available=False)

    assert deposits_blocked_reason() == ""
    payment = initiate_deposit(
        user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
    )
    assert payment.pk is not None


def test_production_ships_with_the_guard_on():
    from config.settings import base

    assert base.VERIFYGH["REQUIRE_CATALOG_FOR_DEPOSIT"] is True


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_the_deposit_endpoint_refuses_with_a_clear_code(api, auth, catalog, depositor):
    ProviderService.objects.update(is_available=False)

    response = deposit(auth(depositor, PASSWORD))

    assert response.status_code == 503
    assert response.data["error"]["code"] == "DEPOSITS_PAUSED"


def test_payment_options_tell_the_ui_deposits_are_paused(api, catalog):
    ProviderService.objects.update(is_available=False)

    response = api.get(OPTIONS)

    assert response.status_code == 200
    assert response.data["deposits_enabled"] is False
    assert response.data["deposits_disabled_reason"]


def test_payment_options_report_deposits_open_when_stocked(api, catalog):
    response = api.get(OPTIONS)

    assert response.data["deposits_enabled"] is True
    assert response.data["deposits_disabled_reason"] == ""


# ---------------------------------------------------------------------------
# What the guard must NOT do
# ---------------------------------------------------------------------------


def test_an_existing_balance_is_untouched_while_deposits_are_paused(
    catalog, depositor, funded_wallet
):
    """Closing the till must not touch what is already in the wallet."""
    funded_wallet(depositor, "50.00")
    ProviderService.objects.update(is_available=False)

    with pytest.raises(ServiceUnavailable):
        initiate_deposit(
            user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
        )

    wallet = get_or_create_wallet(depositor)
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("50.00")


def test_an_in_flight_payment_still_settles_while_deposits_are_paused(
    api, auth, catalog, depositor
):
    """The catalogue emptying mid-payment must not strand money already sent.

    Someone who has approved a Mobile Money prompt has parted with real cash. If
    the last offering sells out in the seconds before their callback lands,
    refusing to credit them would be the exact harm this guard exists to
    prevent: money taken, nothing given back.

    The guard therefore sits on *starting* a deposit, never on settling one.
    """
    from apps.payments.mock import build_webhook
    from apps.payments.models import PaymentStatus

    client = auth(depositor, PASSWORD)
    reference = client.post(
        DEPOSIT,
        {"amount": "20.00", "phone": "0241234599", "network": "MTN"},
        format="json",
    ).data["reference"]

    # The shop shuts while the customer is on the Mobile Money prompt.
    ProviderService.objects.update(is_available=False)
    assert deposits_blocked_reason() != ""

    raw_body, headers = build_webhook(reference=reference, amount="20.00")
    response = api.post(
        "/api/v1/payments/webhooks/mock/",
        data=raw_body,
        content_type="application/json",
        **{"HTTP_X_MOCK_SIGNATURE": headers["X-Mock-Signature"]},
    )

    assert response.status_code == 200
    payment = Payment.objects.get(reference=reference)
    assert payment.status == PaymentStatus.SUCCESS
    wallet = get_or_create_wallet(depositor)
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("20.00"), "money was taken and not credited"


def test_the_readiness_check_is_defined_in_exactly_one_place():
    """The landing page, the deposit guard and the admin panel must agree.

    Three copies of this query would drift until one said "open" while another
    said "shut", and we would be taking money on one screen that another screen
    knew could not be spent.
    """
    import inspect

    from apps.catalog import views as catalog_views
    from apps.payments import services as payment_services

    for module in (catalog_views, payment_services):
        source = inspect.getsource(module)
        assert "is_available=True" not in source, (
            f"{module.__name__} re-implements the readiness query instead of "
            "calling marketplace_readiness()"
        )

def test_offerings_that_cannot_be_priced_do_not_count_as_stock(catalog, depositor):
    """Found in production: 60 purchasable offerings, every one raising
    NoPricingRule because no pricing rule existed.

    Readiness said open, deposits were accepted, and nothing could be bought -
    the precise harm this guard exists to prevent, walking straight through it
    because "purchasable" counted rows rather than quotable prices.
    """
    from apps.pricing.models import PricingRule

    assert marketplace_readiness()["ready"] is True

    PricingRule.objects.all().delete()

    readiness = marketplace_readiness()
    assert readiness["purchasable_offerings"] > 0, "stock is still on the shelves"
    assert readiness["pricing_configured"] is False
    assert readiness["ready"] is False, "open for deposits with nothing quotable"

    with pytest.raises(ServiceUnavailable) as raised:
        initiate_deposit(
            user=depositor, amount=Decimal("20.00"), phone="+233241234599", network="MTN"
        )
    assert raised.value.code == "DEPOSITS_PAUSED"


def test_a_pricing_rule_that_matches_nothing_is_no_rule_at_all(catalog, depositor):
    """Rules are scoped by service and country, so existence is not enough."""
    from apps.catalog.models import Service
    from apps.pricing.models import PricingRule

    orphan = Service.objects.create(slug="nothing-sold-here", name="Nothing")
    PricingRule.objects.all().update(service=orphan)

    assert marketplace_readiness()["ready"] is False
