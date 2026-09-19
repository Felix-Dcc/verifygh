"""TextVerified must stay inert, and fail safe, until it is genuinely configured."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import Country, Provider, ProviderService, Service
from apps.orders.models import Order, OrderStatus
from apps.verification.textverified import TextVerifiedProvider
from apps.wallet.services import get_or_create_wallet

pytestmark = pytest.mark.django_db


def test_no_textverified_endpoint_is_invented():
    """Every path is blank until filled in from the official documentation."""
    paths = [value for name, value in vars(TextVerifiedProvider).items()
             if name.startswith("PATH_") or name == "BASE_URL"]
    assert paths, "expected endpoint constants to exist"
    assert all(value == "" for value in paths)
    assert TextVerifiedProvider.STATE_MAP == {}


def test_a_catalog_sync_against_unconfigured_textverified_fails_cleanly(db):
    from apps.catalog.services import sync_catalog

    summary = sync_catalog("textverified")

    assert summary["errors"], "an unconfigured provider must report, not pretend"
    assert summary["offerings"] == 0
    assert not ProviderService.objects.filter(provider__adapter_key="textverified").exists()


def test_an_order_that_reaches_unconfigured_textverified_is_refunded(
    user, auth, exchange_rate, pricing_rule, funded_wallet, django_capture_on_commit_callbacks
):
    """If an offering somehow exists, the customer still cannot lose money."""
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

    order = Order.objects.get(reference=response.data["reference"])
    assert order.status == OrderStatus.REFUNDED
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
