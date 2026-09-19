"""Every user-owned object, probed from another account.

A single missing owner filter is a data breach, so this is written as a sweep
over every endpoint rather than a spot check. Anything not the caller's must be
indistinguishable from something that does not exist (404, never 403).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.wallet.models import WalletLedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def victim_objects(user, auth, catalog, funded_wallet, django_capture_on_commit_callbacks):
    from apps.verification import mock

    mock.force_scenario("HAPPY")
    funded_wallet(user, "200.00")
    client = auth(user)
    with django_capture_on_commit_callbacks(execute=True):
        order_ref = client.post("/api/v1/orders/", {"service": "instagram", "country": "US"},
                                format="json").data["reference"]
    payment = Payment.objects.create(
        user=user, reference="VGH-PAY-VICTIM01", provider="mock",
        amount=Decimal("20.00"), phone="+233241234567", network="MTN",
    )
    return {
        "order": order_ref,
        "payment": payment.reference,
        "transaction": str(WalletLedgerEntry.objects.filter(wallet__user=user).first().id),
        "notification": str(Notification.objects.filter(user=user).first().id),
    }


@pytest.fixture
def intruder(other_user):
    client = APIClient()
    login = client.post("/api/v1/auth/login/",
                        {"email": other_user.email, "password": "Correct-Horse-Battery-2"},
                        format="json")
    client.credentials(HTTP_X_CSRF_TOKEN=login.data["csrf_token"])
    return client


PROBES = [
    ("get", "/api/v1/orders/{order}/"),
    ("get", "/api/v1/orders/{order}/status/"),
    ("post", "/api/v1/orders/{order}/cancel/"),
    ("post", "/api/v1/orders/{order}/complete/"),
    ("get", "/api/v1/payments/{payment}/"),
    ("post", "/api/v1/payments/{payment}/refresh/"),
    ("get", "/api/v1/transactions/{transaction}/"),
    ("post", "/api/v1/notifications/{notification}/read/"),
]


@pytest.mark.parametrize(("method", "template"), PROBES)
def test_another_users_object_looks_like_it_does_not_exist(
    intruder, victim_objects, method, template
):
    url = template.format(**victim_objects)
    response = getattr(intruder, method)(url, {}, format="json")
    assert response.status_code == 404, f"{method.upper()} {url} -> {response.status_code}"


def test_list_endpoints_never_include_another_users_rows(intruder, victim_objects):
    for url in ("/api/v1/orders/", "/api/v1/payments/", "/api/v1/transactions/",
                "/api/v1/notifications/"):
        assert intruder.get(url).data["pagination"]["count"] == 0, url


def test_the_wallet_endpoint_has_no_id_to_guess(intruder, victim_objects):
    assert intruder.get("/api/v1/wallet/").data["balance"] == "0.00"


PROTECTED = [
    "/api/v1/auth/me/", "/api/v1/wallet/", "/api/v1/wallet/summary/",
    "/api/v1/transactions/", "/api/v1/payments/", "/api/v1/orders/",
    "/api/v1/orders/active/", "/api/v1/orders/eligibility/",
    "/api/v1/notifications/", "/api/v1/notifications/unread/",
]


@pytest.mark.parametrize("url", PROTECTED)
def test_every_account_endpoint_requires_authentication(api, url):
    assert api.get(url).status_code == 401
