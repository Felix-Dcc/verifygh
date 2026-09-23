"""Hubtel must stay inert, and fail safe, until it is genuinely implemented.

Hubtel's API reference sits behind a merchant account, so this adapter's
endpoints are blank. These tests exist so that state is explicit and cannot
drift: nobody can half-fill it in, and nobody can deploy it by accident.

They also fail if someone guesses an endpoint - which is the failure mode this
whole approach exists to prevent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.common.errors import ServiceUnavailable
from apps.payments.hubtel import HubtelProvider
from apps.payments.registry import available_adapters, get_payment_provider, webhook_providers

pytestmark = pytest.mark.django_db


def test_no_hubtel_endpoint_is_invented():
    """Every path is blank until it comes from the official documentation."""
    paths = [value for name, value in vars(HubtelProvider).items()
             if name.startswith("PATH_") or name in ("BASE_URL", "AUTH_SCHEME")]
    assert paths, "expected endpoint constants to exist"
    assert all(value == "" for value in paths), f"an endpoint was filled in: {paths}"
    assert HubtelProvider.NETWORK_CHANNELS == {}
    assert HubtelProvider.STATUS_MAP == {}


def test_the_adapter_reports_itself_unimplemented():
    provider = get_payment_provider("hubtel")

    assert provider.is_implemented is False
    assert provider.is_configured is False
    assert provider.health_check() is False


def test_it_is_registered_so_configuration_can_select_it():
    assert "hubtel" in available_adapters()


def test_starting_a_charge_fails_cleanly(settings):
    """A deposit must fail loudly, not look like it worked."""
    settings.PAYMENT_CREDENTIALS = {
        **settings.PAYMENT_CREDENTIALS,
        "hubtel": {"client_id": "id", "client_secret": "secret",
                   "merchant_account": "1234", "base_url": ""},
    }
    provider = get_payment_provider("hubtel")

    with pytest.raises(ServiceUnavailable) as excinfo:
        provider.initiate_charge(amount=Decimal("50.00"), currency="GHS",
                                 phone="+233241234567", network="MTN",
                                 reference="VGH-PAY-HUBTEL01")
    assert excinfo.value.code == "PAYMENT_PROVIDER_NOT_CONFIGURED"


def test_a_status_lookup_fails_cleanly():
    provider = get_payment_provider("hubtel")
    with pytest.raises(ServiceUnavailable):
        provider.fetch_charge("VGH-PAY-HUBTEL01")


def test_an_unproven_callback_is_never_trusted():
    """Until the documentation says how to prove a callback is genuine, it is
    a stranger's HTTP request and verifies as false."""
    provider = get_payment_provider("hubtel")

    assert provider.verify_webhook(b'{"Status":"Success","Amount":500}', {}) is False
    assert HubtelProvider.CALLBACKS_ARE_SIGNED is False


def test_a_hubtel_callback_cannot_credit_a_wallet(api, user, settings):
    """End to end through the real endpoint: an unverifiable callback answers
    401 and moves no money, whatever it claims."""
    from decimal import Decimal as D

    from apps.payments.models import Payment
    from apps.wallet.services import get_or_create_wallet

    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "hubtel",
                         "WEBHOOK_PROVIDERS": []}
    payment = Payment.objects.create(
        user=user, reference="VGH-PAY-HUBTEL02", provider="hubtel",
        amount=D("50.00"), phone="+233241234567", network="MTN",
    )

    response = api.post(
        "/api/v1/payments/webhooks/hubtel/",
        data=b'{"ResponseCode":"0000","Data":{"ClientReference":"VGH-PAY-HUBTEL02",'
             b'"Amount":50.00,"Status":"Success"}}',
        content_type="application/json",
    )

    assert response.status_code == 401
    payment.refresh_from_db()
    assert payment.status == "PENDING"
    assert get_or_create_wallet(user).balance == Decimal("0.00")


def test_only_the_active_provider_can_receive_callbacks(settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "hubtel",
                         "WEBHOOK_PROVIDERS": []}
    assert webhook_providers() == {"hubtel"}

    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "paystack",
                         "WEBHOOK_PROVIDERS": []}
    assert "hubtel" not in webhook_providers()


def test_the_adapter_makes_no_network_call_while_unimplemented(monkeypatch):
    """Nothing here should reach the internet - there is no address to reach."""
    import requests

    def explode(*args, **kwargs):
        raise AssertionError("the unimplemented adapter attempted a network call")

    monkeypatch.setattr(requests.Session, "request", explode)
    provider = get_payment_provider("hubtel")

    for call in (
        lambda: provider.initiate_charge(amount=Decimal("1.00"), currency="GHS",
                                         phone="+233241234567", network="MTN",
                                         reference="VGH-PAY-HUBTEL03"),
        lambda: provider.fetch_charge("VGH-PAY-HUBTEL03"),
        lambda: provider.parse_webhook(b"{}", {}),
    ):
        with pytest.raises(ServiceUnavailable):
            call()


def test_the_implemented_list_matches_what_the_adapters_report():
    """The boot guard reads a plain data module, because settings cannot import
    the adapters. This binds the two so they cannot drift apart - fill in
    hubtel.py and this test tells you to update the list."""
    from apps.payments.implemented import IMPLEMENTED_PAYMENT_PROVIDERS
    from apps.payments.registry import available_adapters, get_payment_provider

    for key in available_adapters():
        provider = get_payment_provider(key)
        # Adapters without the attribute (mock, paystack) are implemented.
        implemented = getattr(provider, "is_implemented", True)
        assert implemented == (key in IMPLEMENTED_PAYMENT_PROVIDERS), (
            f"{key}: adapter says implemented={implemented}, but "
            f"IMPLEMENTED_PAYMENT_PROVIDERS says {key in IMPLEMENTED_PAYMENT_PROVIDERS}. "
            "Update apps/payments/implemented.py."
        )
