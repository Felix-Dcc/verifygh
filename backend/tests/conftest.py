from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.catalog.services import sync_catalog
from apps.pricing.models import MarkupType, PricingRule, Rounding
from apps.pricing.rates import record_rate
from apps.wallet.models import LedgerDirection, LedgerEntryType
from apps.wallet.services import get_or_create_wallet, post_entry


@pytest.fixture(autouse=True)
def _reset_mock_providers():
    """Never let one test's forced scenario leak into the next."""
    from apps.payments import mock as payment_mock
    from apps.verification import mock as verification_mock

    verification_mock.force_scenario(None)
    payment_mock.force_outcome(None)
    yield
    verification_mock.force_scenario(None)
    payment_mock.force_outcome(None)


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def exchange_rate(db):
    return record_rate(Decimal("12.00"), source="test")


@pytest.fixture
def pricing_rule(db):
    return PricingRule.objects.create(
        name="Test global default",
        service=None,
        country=None,
        markup_type=MarkupType.PERCENTAGE,
        markup_percent=Decimal("20.00"),
        payment_fee_percent=Decimal("0.00"),
        risk_buffer_percent=Decimal("0.00"),
        rounding=Rounding.NONE,
        min_price=Decimal("0.50"),
        max_price=Decimal("500.00"),
        priority=1000,
    )


@pytest.fixture
def catalog(db, exchange_rate, pricing_rule):
    """A fully synced mock catalog, ready to price and sell."""
    return sync_catalog("mock")


@pytest.fixture
def user(db) -> User:
    account = User.objects.create_user(
        email="kwame@example.com",
        password="Correct-Horse-Battery-1",
        full_name="Kwame Mensah",
        phone="+233241234567",
    )
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


@pytest.fixture
def other_user(db) -> User:
    account = User.objects.create_user(
        email="ama@example.com", password="Correct-Horse-Battery-2", full_name="Ama Owusu"
    )
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_user(
        email="admin@verifygh.local",
        password="Correct-Horse-Battery-3",
        role=Role.SUPER_ADMIN,
        is_email_verified=True,
    )


@pytest.fixture
def support_user(db) -> User:
    return User.objects.create_user(
        email="support@verifygh.local",
        password="Correct-Horse-Battery-4",
        role=Role.SUPPORT,
        is_email_verified=True,
    )


@pytest.fixture
def auth(api):
    """Sign a user in and wire up the CSRF header the cookie auth requires."""

    def _auth(account: User, password: str = "Correct-Horse-Battery-1") -> APIClient:
        response = api.post(
            "/api/v1/auth/login/", {"email": account.email, "password": password}, format="json"
        )
        assert response.status_code == 200, response.data
        api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
        return api

    return _auth


@pytest.fixture
def funded_wallet():
    """Put money in a wallet the same way a deposit would: through the ledger."""

    def _fund(account: User, amount: str = "200.00"):
        wallet = get_or_create_wallet(account)
        post_entry(
            wallet=wallet,
            amount=Decimal(amount),
            entry_type=LedgerEntryType.DEPOSIT,
            direction=LedgerDirection.CREDIT,
            idempotency_key=f"test-fund:{account.pk}:{amount}",
            description="Test funding",
            counterparty="TEST",
        )
        wallet.refresh_from_db()
        return wallet

    return _fund


def pytest_sessionstart(session):
    """In CI the suite must run on PostgreSQL, or its concurrency results mean
    nothing. REQUIRE_POSTGRES=1 turns a silent SQLite fallback (a typo in
    DATABASE_URL, a missing service container) into a hard failure."""
    import os

    if os.environ.get("REQUIRE_POSTGRES") != "1":
        return
    engine = settings.DATABASES["default"]["ENGINE"]
    if "postgresql" not in engine:
        pytest.exit(f"REQUIRE_POSTGRES=1 but the database engine is {engine!r}.", returncode=3)


@pytest.fixture
def brevo(settings, monkeypatch):
    """Send email through the real Brevo backend, against a fake Brevo API.

    Nothing leaves the machine: `requests.Session.post` is replaced, every call
    is recorded in `brevo.calls`, and `brevo.replies` queues what the fake
    answers - a (status, body) pair or an exception - 201 when empty.
    """
    from types import SimpleNamespace

    import requests

    settings.EMAIL_BACKEND = "apps.notifications.brevo.BrevoEmailBackend"
    settings.BREVO_API_KEY = "xkeysib-test-key-not-real"
    settings.DEFAULT_FROM_EMAIL = '"VerifyGH" <support@getverifygh.com>'
    state = SimpleNamespace(calls=[], replies=[])

    class FakeResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    def fake_post(self, url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append({"url": url, "json": json, "headers": headers or {},
                            "timeout": timeout})
        reply = state.replies.pop(0) if state.replies else (201, {"messageId": "<t@brevo>"})
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(*reply)

    monkeypatch.setattr(requests.Session, "post", fake_post)
    return state
