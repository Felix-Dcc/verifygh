"""The TextVerified adapter, against responses shaped like the published spec.

No network: every response here mirrors the schemas in TextVerified's OpenAPI
document, so the tests fail if the adapter stops speaking that shape. The
matching live tests (`test_textverified_live.py`) run the same flows against
the provider's documented mock data, and are skipped without an API key.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import requests

from apps.common.errors import ProviderError, ServiceUnavailable
from apps.verification.base import ProviderOrderState
from apps.verification.textverified import TextVerifiedProvider

pytestmark = pytest.mark.django_db

BASE = "https://www.textverified.com"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = b"{}" if payload is None else b'{"x":1}'

    def json(self):
        if self._payload == "not-json":
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def configured(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "textverified": {"api_key": "test-key", "api_username": "ops@verifygh.test",
                         "base_url": BASE},
    }
    return TextVerifiedProvider()


@pytest.fixture
def transport(monkeypatch):
    """Records every request and replies from a routing table."""
    calls: list[dict] = []
    routes: dict[tuple[str, str], object] = {}

    def fake_request(self, method, url, headers=None, json=None, params=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers or {},
                      "json": json, "params": params})
        path = url.replace(BASE, "")
        handler = routes.get((method, path))
        if handler is None:
            raise AssertionError(f"unexpected call: {method} {path}")
        return handler(json, params) if callable(handler) else handler

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return {"calls": calls, "routes": routes}


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    """The pause before retrying an "Unavailable" purchase is real time; not here."""
    from apps.verification import textverified

    monkeypatch.setattr(textverified, "UNAVAILABLE_RETRY_SECONDS", 0)


def auth_route(transport, token="tok-123"):
    transport["routes"][("POST", "/api/pub/v2/auth")] = FakeResponse(
        200, {"token": token, "expiresIn": 3600,
              "expiresAt": "2099-01-01T00:00:00Z"}
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_the_api_key_is_exchanged_for_a_bearer_token(configured, transport):
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/account/me")] = FakeResponse(
        200, {"username": "ops", "currentBalance": 12.5}
    )

    assert configured.health_check() is True

    auth_call = transport["calls"][0]
    assert auth_call["url"] == f"{BASE}/api/pub/v2/auth"
    # The documented header pair, not a query string or basic auth.
    assert auth_call["headers"]["X-API-USERNAME"] == "ops@verifygh.test"
    assert auth_call["headers"]["X-API-KEY"] == "test-key"
    # Every later call carries the bearer token.
    assert transport["calls"][1]["headers"]["Authorization"] == "Bearer tok-123"


def test_the_token_is_reused_rather_than_refetched(configured, transport):
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/account/me")] = FakeResponse(
        200, {"currentBalance": 1}
    )

    configured.health_check()
    configured.health_check()

    auths = [c for c in transport["calls"] if c["url"].endswith("/auth")]
    assert len(auths) == 1, "re-authenticating on every call wastes the rate limit"


def test_an_unconfigured_provider_makes_no_call(settings):
    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "textverified": {"api_key": "", "api_username": "",
                                                      "base_url": BASE}}
    provider = TextVerifiedProvider()

    assert provider.is_configured is False
    assert provider.health_check() is False
    with pytest.raises(ServiceUnavailable):
        provider.get_pricing("instagram", "US")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_services_are_listed_with_their_price(configured, transport):
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/services")] = FakeResponse(200, [
        {"serviceName": "instagram", "description": "Instagram", "capability": "sms"},
        {"serviceName": "whatsapp", "description": "WhatsApp", "capability": "sms"},
    ])
    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = lambda body, params: (
        FakeResponse(200, {"serviceName": body["serviceName"],
                           "price": 0.75 if body["serviceName"] == "instagram" else 1.20})
    )

    services = configured.get_services()

    assert [s.code for s in services] == ["instagram", "whatsapp"]
    assert services[0].cost == Decimal("0.75")
    assert services[1].cost == Decimal("1.20")
    assert all(s.currency == "USD" and s.country_code == "US" for s in services)


def test_a_service_that_cannot_be_priced_is_left_out(configured, transport):
    """An unpriced service would be sold at a guessed price."""
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/services")] = FakeResponse(200, [
        {"serviceName": "good", "description": "Good"},
        {"serviceName": "broken", "description": "Broken"},
    ])

    def pricing(body, params):
        if body["serviceName"] == "broken":
            return FakeResponse(400, {"errorCode": "PricingFailure"})
        return FakeResponse(200, {"price": 0.5})

    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = pricing

    services = configured.get_services()

    assert [s.code for s in services] == ["good"]


def test_the_catalogue_sync_is_bounded(configured, transport, settings):
    """The service list and the price are separate calls upstream."""
    settings.VERIFYGH = {**settings.VERIFYGH, "PROVIDER_CATALOG_LIMIT": 2}
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/services")] = FakeResponse(
        200, [{"serviceName": f"svc{i}"} for i in range(10)]
    )
    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = FakeResponse(
        200, {"price": 1.0}
    )

    services = configured.get_services()

    assert len(services) == 2
    pricing_calls = [c for c in transport["calls"] if c["url"].endswith("/pricing/verifications")]
    assert len(pricing_calls) == 2


def test_countries_report_only_what_can_be_sourced(configured):
    countries = configured.get_countries()

    assert [c.code for c in countries] == ["US"]


def test_availability_reads_the_inventory_endpoint(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/inventory/verifications")] = FakeResponse(
        200, {"availableQuantity": 7}
    )

    availability = configured.get_availability("instagram", "US")

    assert availability.available is True
    assert availability.count == 7
    body = transport["calls"][-1]["json"]
    assert body == {"serviceName": "instagram", "numberType": "mobile", "capability": "sms"}


def test_zero_inventory_reads_as_unavailable(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/inventory/verifications")] = FakeResponse(
        200, {"availableQuantity": 0}
    )

    assert configured.get_availability("instagram", "US").available is False


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def order_routes(transport, *, state="verificationPending", number="+12025550142", sms=None):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = FakeResponse(
        200, {"price": 0.75}
    )
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        201, {"method": "GET", "href": "/api/pub/v2/verifications/ver_1"}
    )
    transport["routes"][("GET", "/api/pub/v2/verifications/ver_1")] = FakeResponse(200, {
        "id": "ver_1", "number": number, "state": state, "serviceName": "instagram",
        "endsAt": "2099-01-01T00:20:00Z", "totalCost": 0.75,
        "sms": {"method": "GET", "href": "/api/pub/v2/sms?reservationId=ver_1"},
    })
    transport["routes"][("GET", "/api/pub/v2/sms?reservationId=ver_1")] = FakeResponse(
        200, {"data": sms or []}
    )
    transport["routes"][("GET", "/api/pub/v2/sms")] = lambda body, params: FakeResponse(
        200, {"data": sms or []}
    )


def test_creating_an_order_reserves_a_number(configured, transport):
    order_routes(transport)

    order = configured.create_order("instagram", "US", "order:abc")

    assert order.provider_order_id == "ver_1"
    assert order.phone_number == "+12025550142"
    assert order.state is ProviderOrderState.WAITING_FOR_CODE
    assert order.expires_at is not None


def test_the_idempotency_key_is_forwarded(configured, transport):
    """A retry after a timeout must not reserve - and bill us for - two numbers."""
    order_routes(transport)

    configured.create_order("instagram", "US", "order:abc")

    create = next(c for c in transport["calls"] if c["url"].endswith("/v2/verifications"))
    assert create["headers"]["Idempotency-Key"] == "order:abc"


def test_a_maximum_price_is_sent_so_a_price_move_cannot_bill_us_more(configured, transport):
    order_routes(transport)

    configured.create_order("instagram", "US", "order:abc")

    create = next(c for c in transport["calls"] if c["url"].endswith("/v2/verifications"))
    # 0.75 quoted, 5% tolerance.
    assert create["json"]["maxPrice"] == pytest.approx(0.79, abs=0.01)
    assert create["json"]["serviceName"] == "instagram"
    assert create["json"]["capability"] == "sms"


def test_a_pricing_failure_surfaces_as_a_clean_error(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = FakeResponse(
        200, {"price": 0.75}
    )
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        400, {"errorCode": "PricingFailure", "errorDescription": "maxPrice too low"}
    )

    with pytest.raises(ProviderError) as excinfo:
        configured.create_order("instagram", "US", "order:abc")

    message = str(excinfo.value)
    assert "price has changed" in message
    # The provider's own wording never reaches the customer.
    assert "maxPrice" not in message


def test_a_momentary_shortage_is_retried_once_under_a_new_key(configured, transport):
    """Unavailable reserved nothing; the same number can often be bought seconds later."""
    order_routes(transport)
    replies = iter([
        FakeResponse(400, {"errorCode": "Unavailable", "errorDescription": "No stock"}),
        FakeResponse(201, {"method": "GET", "href": "/api/pub/v2/verifications/ver_1"}),
    ])
    transport["routes"][("POST", "/api/pub/v2/verifications")] = lambda body, params: next(replies)

    order = configured.create_order("instagram", "US", "order:abc")

    assert order.provider_order_id == "ver_1"
    creates = [c for c in transport["calls"] if c["url"].endswith("/v2/verifications")]
    # The first key would replay the 400; the retry has its own.
    assert [c["headers"]["Idempotency-Key"] for c in creates] == ["order:abc", "order:abc:retry"]
    assert creates[0]["json"] == creates[1]["json"]


def test_a_shortage_that_lasts_is_not_retried_again(configured, transport):
    order_routes(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        400, {"errorCode": "Unavailable"}
    )

    with pytest.raises(ProviderError) as excinfo:
        configured.create_order("instagram", "US", "order:abc")

    assert excinfo.value.provider_code == "Unavailable"
    creates = [c for c in transport["calls"] if c["url"].endswith("/v2/verifications")]
    assert len(creates) == 2


def test_other_refusals_are_not_retried(configured, transport):
    order_routes(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        400, {"errorCode": "PricingFailure"}
    )

    with pytest.raises(ProviderError):
        configured.create_order("instagram", "US", "order:abc")

    creates = [c for c in transport["calls"] if c["url"].endswith("/v2/verifications")]
    assert len(creates) == 1


def test_the_providers_reason_is_logged_for_staff_with_numbers_masked(configured, transport,
                                                                      caplog):
    import logging

    order_routes(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        400, {"errorCode": "PricingFailure",
              "errorDescription": "Price 1.80 is above maxPrice for 12025550142"}
    )
    # The app's loggers do not propagate to the root, so listen on them directly.
    app_logger = logging.getLogger("verifygh")
    app_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="verifygh"), pytest.raises(ProviderError):
            configured.create_order("instagram", "US", "order:abc")
    finally:
        app_logger.removeHandler(caplog.handler)

    logged = [r for r in caplog.records if r.getMessage() == "textverified_error"]
    assert logged and "above maxPrice" in logged[0].provider_description
    assert "12025550142" not in logged[0].provider_description
    refused = [r for r in caplog.records if r.getMessage() == "textverified_create_refused"]
    assert refused and refused[0].max_price == "0.79"


@pytest.mark.parametrize(("error_code", "expected"), [
    ("InsufficientBalance", "temporarily unavailable"),
    ("Unavailable", "No number is available"),
    ("TooManyUnfinishedVerifications", "a lot of orders"),
])
def test_documented_create_errors_are_translated(configured, transport, error_code, expected):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/pricing/verifications")] = FakeResponse(
        200, {"price": 0.75}
    )
    transport["routes"][("POST", "/api/pub/v2/verifications")] = FakeResponse(
        400, {"errorCode": error_code}
    )

    with pytest.raises(ProviderError, match=expected):
        configured.create_order("instagram", "US", "order:abc")


# ---------------------------------------------------------------------------
# Codes and states
# ---------------------------------------------------------------------------


def test_a_completed_verification_carries_its_code(configured, transport):
    order_routes(transport, state="verificationCompleted", sms=[{
        "id": "sms_1", "from": "+12025550100", "to": "+12025550142",
        "createdAt": "2026-01-01T00:05:00Z", "smsContent": "Your code is 123456",
        "parsedCode": "123456",
    }])

    order = configured.get_order_status("ver_1")

    assert order.state is ProviderOrderState.CODE_RECEIVED
    assert order.code is not None
    assert order.code.code == "123456"
    assert order.code.full_text == "Your code is 123456"


def test_a_pending_verification_has_no_code(configured, transport):
    order_routes(transport, state="verificationPending")

    order = configured.get_order_status("ver_1")

    assert order.state is ProviderOrderState.WAITING_FOR_CODE
    assert order.code is None


@pytest.mark.parametrize(("provider_state", "expected"), [
    ("verificationPending", ProviderOrderState.WAITING_FOR_CODE),
    ("verificationCompleted", ProviderOrderState.CODE_RECEIVED),
    ("verificationReused", ProviderOrderState.CODE_RECEIVED),
    ("verificationReactivated", ProviderOrderState.WAITING_FOR_CODE),
    ("verificationCanceled", ProviderOrderState.CANCELLED),
    ("verificationRefunded", ProviderOrderState.CANCELLED),
    ("verificationTimedOut", ProviderOrderState.EXPIRED),
    ("verificationReported", ProviderOrderState.FAILED),
])
def test_every_documented_state_maps(configured, transport, provider_state, expected):
    order_routes(transport, state=provider_state, sms=[{"parsedCode": "1", "smsContent": "1"}])

    assert configured.get_order_status("ver_1").state is expected


def test_an_unknown_state_never_reads_as_finished(configured, transport):
    """A state we have not seen must not look like a delivered service."""
    order_routes(transport, state="somethingNewUpstream")

    order = configured.get_order_status("ver_1")

    assert order.state is ProviderOrderState.PENDING
    assert order.code is None


def test_a_pending_state_without_a_number_is_not_waiting_for_a_code(configured, transport):
    order_routes(transport, state="verificationPending", number="")

    assert configured.get_order_status("ver_1").state is ProviderOrderState.PENDING


# ---------------------------------------------------------------------------
# Cancel, report, and failure handling
# ---------------------------------------------------------------------------


def test_cancelling_uses_the_documented_endpoint(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications/ver_1/cancel")] = FakeResponse(200, {})

    assert configured.cancel_order("ver_1") is True


def test_a_refused_cancellation_is_not_an_error(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications/ver_1/cancel")] = FakeResponse(
        400, {"errorCode": "ProcessingError"}
    )

    assert configured.cancel_order("ver_1") is False


def test_a_refund_reports_the_verification(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/verifications/ver_1/report")] = FakeResponse(200, {})

    assert configured.refund_order("ver_1") is True


def test_a_rate_limit_is_backed_off_not_retried_through(configured, transport):
    auth_route(transport)
    transport["routes"][("POST", "/api/pub/v2/inventory/verifications")] = FakeResponse(429, {})

    with pytest.raises(ServiceUnavailable) as excinfo:
        configured.get_availability("instagram", "US")

    assert excinfo.value.code == "PROVIDER_RATE_LIMITED"


def test_a_timeout_is_reported_without_provider_internals(configured, transport, monkeypatch):
    auth_route(transport)

    def timeout(*args, **kwargs):
        raise requests.Timeout("connection timed out to www.textverified.com")

    monkeypatch.setattr(requests.Session, "request", timeout)

    with pytest.raises(ProviderError) as excinfo:
        configured.get_pricing("instagram", "US")

    assert "textverified.com" not in str(excinfo.value)


def test_the_account_balance_is_readable_for_the_admin_health_page(configured, transport):
    auth_route(transport)
    transport["routes"][("GET", "/api/pub/v2/account/me")] = FakeResponse(
        200, {"username": "ops", "currentBalance": 42.5}
    )

    assert configured.account_balance() == Decimal("42.5")
