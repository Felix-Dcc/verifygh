"""TextVerified must fail safe until it is genuinely configured and authorised."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import Country, Provider, ProviderService, Service
from apps.orders.models import Order
from apps.verification.textverified import TextVerifiedProvider
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db


def _published_spec() -> dict:
    """TextVerified's own published API definition, kept in the repository.

    Generated from https://backend.textverified.com/swagger/v2/swagger.json so
    the adapter can be checked against the vendor's document rather than
    against someone's memory of it.
    """
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "apps/verification/textverified_endpoints.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_textverified_endpoint_is_invented():
    """Every endpoint the adapter calls appears in the published specification.

    This is the guard that replaced "all paths must be blank" once the
    documentation was in hand. It fails on a typo, a version drift, or a path
    someone invented because it looked plausible.
    """
    spec = _published_spec()
    documented = set(spec["paths"])

    used = {name: value for name, value in vars(TextVerifiedProvider).items()
            if name.startswith("PATH_") and value}
    assert used, "expected endpoint constants to be filled in"

    for name, path in used.items():
        # {id} is how the specification itself writes path parameters.
        assert path in documented, f"{name}={path} is not in the published specification"

    assert TextVerifiedProvider.BASE_URL in spec["servers"]


def test_every_mapped_state_is_a_documented_state():
    """A state we invented would silently never match, leaving orders stuck."""
    spec = _published_spec()
    documented = {state.lower() for state in spec["verification_states"]}

    for state in TextVerifiedProvider.STATE_MAP:
        assert state in documented, f"{state} is not a documented state"

    # And every documented verification state is handled, so a real one cannot
    # fall through to the unknown-state path unnoticed.
    verification_states = {s for s in documented if s.startswith("verification")
                           and s != "verification"}
    unhandled = verification_states - set(TextVerifiedProvider.STATE_MAP)
    assert not unhandled, f"documented states with no mapping: {sorted(unhandled)}"


def test_an_unconfigured_textverified_sync_reports_and_lists_nothing(db, settings):
    from apps.catalog.services import sync_catalog

    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "textverified": {"api_key": "", "api_username": "",
                                                      "base_url": ""}}
    summary = sync_catalog("textverified")

    assert summary["errors"], "an unconfigured provider must report, not pretend"
    assert not ProviderService.objects.filter(provider__adapter_key="textverified").exists()
    # A real provider's row starts unauthorised: syncing is never permission to sell.
    assert Provider.objects.get(adapter_key="textverified").resale_authorized is False


def test_a_catalog_sync_against_unconfigured_onlinesim_fails_cleanly(db, settings):
    from apps.catalog.services import sync_catalog

    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "onlinesim": {"api_key": "", "base_url": "",
                                                   "currency": "USD"}}
    summary = sync_catalog("onlinesim")

    assert summary["errors"], "an unconfigured provider must report, not pretend"
    assert summary["offerings"] == 0


def test_an_order_that_reaches_a_removed_provider_charges_nothing(
    user, auth, exchange_rate, pricing_rule, funded_wallet, django_capture_on_commit_callbacks
):
    """If an offering somehow exists, the customer still cannot lose money.

    The live stock check asks the provider before any money moves, so a
    provider that is no longer registered is refused up front rather than
    charged and refunded.
    """
    provider = Provider.objects.create(adapter_key="textverified", name="TextVerified")
    ProviderService.objects.create(
        provider=provider,
        service=Service.objects.create(slug="probe", name="Probe"),
        country=Country.objects.create(code="US", name="United States", dial_code="+1"),
        provider_service_code="probe",
        cost_amount=Decimal("1.0000"),
    )
    funded_wallet(user, "100.00")
    client = auth(user)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post("/api/v1/orders/", {"service": "probe", "country": "US"},
                               format="json")

    assert response.status_code == 503
    assert not Order.objects.exists()
    assert get_or_create_wallet(user).balance == Decimal("100.00")


def test_production_refuses_to_sell_mock_numbers(monkeypatch):
    import importlib
    import sys

    from django.core.exceptions import ImproperlyConfigured

    env = {
        "SECRET_KEY": "x" * 60, "JWT_SIGNING_KEY": "y" * 60,
        "DATABASE_URL": "postgres://u:p@h/d",
        "REDIS_URL": "redis://h", "ALLOWED_HOSTS": "api.example.com",
        "CORS_ALLOWED_ORIGINS": "https://example.com", "FRONTEND_URL": "https://example.com",
        "PAYMENT_PROVIDER": "paystack", "PAYSTACK_SECRET_KEY": "sk_test_x",
        "VERIFICATION_PROVIDER": "mock", "ALLOW_MOCK_VERIFICATION_IN_PRODUCTION": "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    for name in ("config.settings.prod", "config.settings.base"):
        sys.modules.pop(name, None)
    try:
        with pytest.raises(ImproperlyConfigured, match="simulated numbers"):
            importlib.import_module("config.settings.prod")
    finally:
        for name in ("config.settings.prod", "config.settings.base"):
            sys.modules.pop(name, None)
