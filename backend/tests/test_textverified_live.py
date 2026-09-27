"""Contract tests against TextVerified's own mock data. Skipped without a key.

The unit tests in `test_textverified.py` prove the adapter handles the shapes
the specification describes. These prove the specification is still true - that
the live API answers the way it is documented to - which is the part no amount
of local mocking can tell you.

They use the documented mock service names and ids. Per TextVerified's
documentation: mock requests create no real phone numbers and no billing
events, so running these costs nothing and reserves nothing.

To run:

    TEXTVERIFIED_API_KEY=... TEXTVERIFIED_API_USERNAME=you@example.com \\
        pytest tests/test_textverified_live.py -v

Without those variables every test here skips, so CI stays green and offline.
"""

from __future__ import annotations

import os

import pytest

from apps.verification.base import ProviderOrderState
from apps.verification.textverified import TextVerifiedProvider

pytestmark = pytest.mark.django_db

HAS_CREDENTIALS = bool(os.environ.get("TEXTVERIFIED_API_KEY")
                       and os.environ.get("TEXTVERIFIED_API_USERNAME"))

live = pytest.mark.skipif(
    not HAS_CREDENTIALS,
    reason="set TEXTVERIFIED_API_KEY and TEXTVERIFIED_API_USERNAME to run live contract tests",
)


@pytest.fixture
def provider(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "textverified": {
            "api_key": os.environ.get("TEXTVERIFIED_API_KEY", ""),
            "api_username": os.environ.get("TEXTVERIFIED_API_USERNAME", ""),
            "base_url": "https://www.textverified.com",
        },
    }
    return TextVerifiedProvider()


@live
def test_the_credentials_authenticate(provider):
    assert provider.health_check() is True
    balance = provider.account_balance()
    assert balance is not None, "the account endpoint should report a balance"


@live
def test_the_service_list_is_readable(provider):
    services = provider.get_services()

    assert services, "expected at least one priced service"
    assert all(service.cost > 0 for service in services)
    assert all(service.currency == "USD" for service in services)


@live
def test_a_mock_verification_completes_with_the_documented_code(provider):
    """`test_success201` is documented to complete with SMS code 123456."""
    order = provider.create_order("test_success201", "US", "verifygh-contract-success")

    assert order.provider_order_id
    status = provider.get_order_status(order.provider_order_id)
    assert status.state is ProviderOrderState.CODE_RECEIVED
    assert status.code is not None
    assert status.code.code == "123456"


@live
def test_a_mock_pending_verification_has_no_code_yet(provider):
    order = provider.create_order("test_pending201", "US", "verifygh-contract-pending")

    status = provider.get_order_status(order.provider_order_id)

    assert status.state in (ProviderOrderState.PENDING, ProviderOrderState.WAITING_FOR_CODE)
    assert status.code is None


@live
def test_a_timed_out_verification_maps_to_expired(provider):
    order = provider.create_order("test_timeout201", "US", "verifygh-contract-timeout")

    status = provider.get_order_status(order.provider_order_id)

    assert status.state is ProviderOrderState.EXPIRED
    assert status.code is None


@live
def test_no_numbers_available_is_a_clean_failure(provider):
    """The customer must get a refund, not a stuck order."""
    from apps.common.errors import ProviderError

    with pytest.raises(ProviderError, match="No number is available"):
        provider.create_order("test_no_numbers", "US", "verifygh-contract-nonumbers")


@live
def test_insufficient_upstream_balance_is_a_clean_failure(provider):
    from apps.common.errors import ProviderError

    with pytest.raises(ProviderError, match="temporarily unavailable"):
        provider.create_order("test_insufficient_balance", "US", "verifygh-contract-balance")


@live
def test_reading_a_fixed_mock_verification(provider):
    """`mock_ver_success` is fixed test data with code 123456."""
    status = provider.get_order_status("mock_ver_success")

    assert status.state is ProviderOrderState.CODE_RECEIVED
    assert status.code is not None
    assert status.code.code == "123456"


@live
def test_a_cancelled_mock_verification_reads_as_cancelled(provider):
    status = provider.get_order_status("mock_ver_cancelled")

    assert status.state is ProviderOrderState.CANCELLED
