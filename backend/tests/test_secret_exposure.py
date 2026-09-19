"""No credential ever leaves the server in an API response.

Distinctive canary values are planted in every secret setting, then every
readable endpoint is fetched as a customer and as a super admin. A canary (or
a password hash, or a raw JWT) in any response body fails the test. The admin
health endpoint is the likeliest leak - it describes provider configuration -
so it is covered by name as well as by the sweep.
"""

from __future__ import annotations

import pytest
from django.conf import settings as django_settings

pytestmark = pytest.mark.django_db

CANARIES = {
    "SECRET_KEY": "canary-django-secret-7f3e",
    "JWT": "canary-jwt-signing-key-long-enough-for-hs256-2b9d",
    "PAYSTACK_SECRET": "sk_live_canary_paystack_91ac",
    "PAYSTACK_PUBLIC": "pk_live_canary_paystack_55de",
    "MOCK_SECRET": "canary-mock-webhook-c41f",
    "TEXTVERIFIED_KEY": "canary-textverified-key-0e6a",
    "TEXTVERIFIED_USER": "canary-textverified-user-8b17",
    "FX_KEY": "canary-fx-api-key-3d52",
}

CUSTOMER_GETS = [
    "/api/v1/auth/me/", "/api/v1/wallet/", "/api/v1/wallet/summary/",
    "/api/v1/transactions/", "/api/v1/payments/", "/api/v1/payments/options/",
    "/api/v1/orders/", "/api/v1/orders/active/", "/api/v1/orders/eligibility/",
    "/api/v1/services/", "/api/v1/services/featured/", "/api/v1/countries/",
    "/api/v1/notifications/", "/api/v1/notifications/unread/", "/api/v1/catalog/health/",
    "/api/v1/orders/quote/?service=instagram&country=US",
]

ADMIN_GETS = [
    "/api/v1/admin/overview/", "/api/v1/admin/charts/", "/api/v1/admin/health/",
    "/api/v1/admin/users/", "/api/v1/admin/orders/", "/api/v1/admin/payments/",
    "/api/v1/admin/refunds/", "/api/v1/admin/services/", "/api/v1/admin/countries/",
    "/api/v1/admin/offerings/", "/api/v1/admin/pricing-rules/",
    "/api/v1/admin/exchange-rates/", "/api/v1/admin/audit/", "/api/v1/admin/admin-actions/",
    "/api/v1/admin/flags/",
]


@pytest.fixture
def canaries(settings):
    settings.SECRET_KEY = CANARIES["SECRET_KEY"]
    settings.SIMPLE_JWT = {**settings.SIMPLE_JWT, "SIGNING_KEY": CANARIES["JWT"]}
    settings.PAYMENT_CREDENTIALS = {
        "paystack": {"secret_key": CANARIES["PAYSTACK_SECRET"],
                     "public_key": CANARIES["PAYSTACK_PUBLIC"],
                     "base_url": "https://api.paystack.co"},
        "mock": {"secret_key": CANARIES["MOCK_SECRET"]},
    }
    settings.PROVIDER_CREDENTIALS = {
        "textverified": {"api_key": CANARIES["TEXTVERIFIED_KEY"],
                         "api_username": CANARIES["TEXTVERIFIED_USER"], "base_url": ""},
    }
    settings.EXCHANGE_RATE_API_KEY = CANARIES["FX_KEY"]
    # simplejwt caches its settings; make it re-read the signing key.
    from rest_framework_simplejwt.settings import api_settings
    api_settings.reload()
    from rest_framework_simplejwt import state
    state.token_backend.signing_key = CANARIES["JWT"]
    yield
    api_settings.reload()
    state.token_backend.signing_key = django_settings.SIMPLE_JWT["SIGNING_KEY"]


def _assert_clean(client, url, account):
    response = client.get(url)
    assert response.status_code < 500, (url, response.status_code)
    body = response.content.decode("utf-8", "replace")
    for name, value in CANARIES.items():
        assert value not in body, f"{url} leaks {name}"
    assert account.password not in body, f"{url} leaks a password hash"
    for cookie in ("vgh_access", "vgh_refresh"):
        jar = client.cookies.get(getattr(django_settings, "AUTH_COOKIE_" + cookie[4:].upper(),
                                         cookie))
        if jar is not None and jar.value:
            assert jar.value not in body, f"{url} echoes a {cookie} token"


def test_customer_endpoints_expose_no_secrets(canaries, user, auth, catalog, funded_wallet):
    funded_wallet(user, "50.00")
    client = auth(user)
    for url in CUSTOMER_GETS:
        _assert_clean(client, url, user)


def test_admin_endpoints_expose_no_secrets(canaries, admin_user, user, auth, catalog,
                                           funded_wallet):
    funded_wallet(user, "50.00")
    client = auth(admin_user, "Correct-Horse-Battery-3")
    for url in ADMIN_GETS + [f"/api/v1/admin/users/{user.id}/",
                             f"/api/v1/admin/users/{user.id}/transactions/",
                             f"/api/v1/admin/users/{user.id}/activity/"]:
        _assert_clean(client, url, admin_user)


def test_login_and_refresh_bodies_carry_no_tokens(user, api):
    """Tokens travel only in httpOnly cookies, never in a body script can read."""
    response = api.post("/api/v1/auth/login/", {"email": user.email,
                                                "password": "Correct-Horse-Battery-1"},
                        format="json")
    access = api.cookies[django_settings.AUTH_COOKIE_ACCESS].value
    refresh = api.cookies[django_settings.AUTH_COOKIE_REFRESH].value
    body = response.content.decode()
    assert access not in body and refresh not in body

    api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    response = api.post("/api/v1/auth/refresh/", {}, format="json")
    body = response.content.decode()
    assert api.cookies[django_settings.AUTH_COOKIE_ACCESS].value not in body
    assert api.cookies[django_settings.AUTH_COOKIE_REFRESH].value not in body


def test_auth_cookies_are_http_only(user, api):
    api.post("/api/v1/auth/login/", {"email": user.email, "password": "Correct-Horse-Battery-1"},
             format="json")
    assert api.cookies[django_settings.AUTH_COOKIE_ACCESS]["httponly"]
    assert api.cookies[django_settings.AUTH_COOKIE_REFRESH]["httponly"]
    # The CSRF cookie is readable on purpose (double submit); it is not a credential.
    assert not api.cookies[django_settings.AUTH_COOKIE_CSRF]["httponly"]


def test_webhook_error_responses_do_not_echo_the_expected_signature(api, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "PAYMENT_PROVIDER": "mock"}
    settings.PAYMENT_CREDENTIALS = {**settings.PAYMENT_CREDENTIALS,
                                    "mock": {"secret_key": CANARIES["MOCK_SECRET"]}}
    from apps.payments.mock import sign

    raw = b'{"event_id":"e1","data":{"reference":"VGH-PAY-X","amount":"1"}}'
    response = api.post("/api/v1/payments/webhooks/mock/", data=raw,
                        content_type="application/json", HTTP_X_MOCK_SIGNATURE="bad")
    body = response.content.decode()
    assert response.status_code == 401
    assert sign(raw) not in body and CANARIES["MOCK_SECRET"] not in body
