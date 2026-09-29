"""TextVerified as the primary provider, behind its resale-authorisation gate.

TextVerified's terms prohibit sharing its numbers with third parties
(docs/PROVIDERS.md), so the integration is complete but switched off until
staff record TextVerified's written permission. These tests pin that down:

* unauthorised, it may be synced, priced and balance-checked, but nothing is
  listed to customers, charged for, or ordered from it;
* authorised, a US purchase runs end to end through the documented API, with
  one number per purchase however often the customer taps, and every provider
  failure refunded;
* the webhook is only a signed prompt to poll; OnlineSim is switched off
  without touching its history; production never falls back to the mock.

No network: responses mirror the schemas in TextVerified's OpenAPI document.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
import requests
from django.db import IntegrityError, transaction

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.audit.models import AdminAction
from apps.catalog.models import Provider, ProviderService
from apps.catalog.services import sync_catalog
from apps.funding import services as funding
from apps.funding.models import AlertKind, BalanceStatus, ProviderAlert
from apps.orders.models import Order, OrderStatus
from apps.orders.services import poll_order
from apps.verification import textverified as tv_module
from apps.wallet.models import LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import get_or_create_wallet, verify_wallet_integrity

pytestmark = pytest.mark.django_db

BASE = "https://www.textverified.com"
ORDERS = "/api/v1/orders/"
MARKET = "/api/v1/marketplace/"
PROVIDERS = "/api/v1/admin/providers/"
WEBHOOK = "/api/v1/verification/webhooks/textverified/"
ADMIN_PASSWORD = "Correct-Horse-Battery-3"
SECRET = "whsec_test-textverified-webhook-secret"


class Reply:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = b"{}" if payload is None else b'{"x":1}'

    def json(self):
        return self._payload


@pytest.fixture
def tv(settings, monkeypatch):
    """Configured TextVerified credentials and a routing-table transport."""
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "textverified": {"api_key": "test-key", "api_username": "ops@verifygh.test",
                         "base_url": BASE, "webhook_secret": SECRET},
    }
    calls: list[dict] = []
    routes: dict = {}

    def fake_request(self, method, url, headers=None, json=None, params=None, timeout=None):
        calls.append({"method": method, "path": url.replace(BASE, ""), "headers": headers or {},
                      "json": json, "params": params})
        handler = routes.get((method, url.replace(BASE, "")))
        if handler is None:
            raise AssertionError(f"unexpected call: {method} {url}")
        return handler(json, params) if callable(handler) else handler

    monkeypatch.setattr(requests.Session, "request", fake_request)
    routes[("POST", "/api/pub/v2/auth")] = Reply(200, {"token": "tok", "expiresIn": 3600,
                                                        "expiresAt": "2099-01-01T00:00:00Z"})
    routes[("GET", "/api/pub/v2/services")] = Reply(200, [
        {"serviceName": "tiktok", "description": "TikTok", "capability": "sms"},
        {"serviceName": "whatsapp", "description": "WhatsApp", "capability": "sms"},
    ])
    prices = {"tiktok": 0.50, "whatsapp": 1.25}
    routes[("POST", "/api/pub/v2/pricing/verifications")] = (
        lambda body, params: Reply(200, {"serviceName": body["serviceName"],
                                         "price": prices[body["serviceName"]]}))
    routes[("POST", "/api/pub/v2/inventory/verifications")] = Reply(200, {"availableQuantity": 40})
    return {"calls": calls, "routes": routes}


def creates(tv) -> list[dict]:
    return [c for c in tv["calls"]
            if c["method"] == "POST" and c["path"] == "/api/pub/v2/verifications"]


@pytest.fixture
def tv_catalog(tv, exchange_rate, pricing_rule):
    summary = sync_catalog("textverified")
    assert not summary["errors"], summary
    return Provider.objects.get(adapter_key="textverified")


def authorise(provider: Provider) -> Provider:
    Provider.objects.filter(pk=provider.pk).update(
        resale_authorized=True, authorization_reference="Test: written permission on file.")
    funding.refresh_marketplace()
    provider.refresh_from_db()
    return provider


def verification_routes(tv, *, state="verificationPending", code=None, vid="ver_1"):
    tv["routes"][("POST", "/api/pub/v2/verifications")] = Reply(
        201, {"href": f"/api/pub/v2/verifications/{vid}", "method": "GET"})
    details = {"id": vid, "number": "+12025550123", "serviceName": "tiktok", "state": state,
               "totalCost": 0.50, "endsAt": "2099-01-01T00:10:00Z",
               "sms": {"href": f"/api/pub/v2/sms?reservationId={vid}", "method": "GET"}}
    tv["routes"][("GET", f"/api/pub/v2/verifications/{vid}")] = Reply(200, details)
    sms = {"data": [{"id": "sms_1", "from": "TikTok", "to": "+12025550123",
                     "createdAt": "2026-09-29T20:00:00Z", "smsContent": f"Your code is {code}",
                     "parsedCode": code, "encrypted": False}]} if code else {"data": []}
    tv["routes"][("GET", f"/api/pub/v2/sms?reservationId={vid}")] = Reply(200, sms)
    tv["routes"][("GET", "/api/pub/v2/sms")] = Reply(200, sms)


def buy(client, capture, service="tiktok", country="US", key=None):
    body = {"service": service, "country": country}
    if key:
        body["idempotency_key"] = key
    with capture(execute=True):
        return client.post(ORDERS, body, format="json")


@pytest.fixture
def buyer(user, funded_wallet):
    funded_wallet(user, "200.00")
    return user


# ---------------------------------------------------------------------------
# Unauthorised: synced and priced, never sold
# ---------------------------------------------------------------------------


def test_unauthorised_textverified_is_priced_for_staff_but_never_listed(tv_catalog, api):
    from apps.pricing.services import listed_offerings

    offerings = ProviderService.objects.filter(provider=tv_catalog)
    assert {o.provider_service_code: o.cost_amount for o in offerings} == {
        "tiktok": Decimal("0.5000"), "whatsapp": Decimal("1.2500")}
    assert tv_catalog.resale_authorized is False

    # Staff can prepare prices...
    assert {o.provider_service_code for o in listed_offerings()} >= {"tiktok", "whatsapp"}
    # ...customers see nothing.
    listed = api.get(MARKET, {"country": "US", "include_unavailable": "true"}).data["results"]
    assert listed == []
    assert api.get(f"{MARKET}tiktok/").data["countries"][0]["offered"] is False


def test_an_unauthorised_provider_is_never_charged_or_called(tv, tv_catalog, buyer, auth,
                                                             django_capture_on_commit_callbacks):
    response = buy(auth(buyer), django_capture_on_commit_callbacks)

    assert response.status_code == 503
    assert not Order.objects.filter(user=buyer).exists()
    assert get_or_create_wallet(buyer).balance == Decimal("200.00")
    assert creates(tv) == []


def test_authorisation_withdrawn_after_the_charge_refunds_without_calling(
        tv, tv_catalog, buyer):
    from apps.orders.services import create_order, fulfil_order

    authorise(tv_catalog)
    order = create_order(user=buyer, service_slug="tiktok", country_code="US",
                         idempotency_key="withdrawn-1")
    assert order.status == OrderStatus.PROCESSING
    Provider.objects.filter(pk=tv_catalog.pk).update(resale_authorized=False)

    order = fulfil_order(Order.objects.select_related("provider").get(pk=order.pk))

    assert order.status == OrderStatus.REFUNDED
    assert creates(tv) == []
    wallet = get_or_create_wallet(buyer)
    assert wallet.balance == Decimal("200.00")
    assert verify_wallet_integrity(wallet)["ok"] is True


# ---------------------------------------------------------------------------
# Recording the authorisation
# ---------------------------------------------------------------------------


@pytest.fixture
def plain_admin(db):
    return User.objects.create_user(email="ops-admin@verifygh.local",
                                    password="Correct-Horse-Battery-1", role=Role.ADMIN,
                                    is_email_verified=True)


def test_only_provider_managers_record_authorisation_and_it_needs_evidence(
        tv_catalog, auth, admin_user, plain_admin, api):
    url = f"{PROVIDERS}textverified/authorization/"
    ops = auth(plain_admin)
    assert ops.get(PROVIDERS).status_code == 200
    assert ops.post(url, {"authorized": True, "reference": "x" * 20, "reason": "go live"},
                    format="json").status_code == 403
    api.credentials()

    boss = auth(admin_user, ADMIN_PASSWORD)
    no_evidence = boss.post(url, {"authorized": True, "reference": "ok", "reason": "go live"},
                            format="json")
    assert no_evidence.status_code == 400

    granted = boss.post(url, {
        "authorized": True,
        "reference": "Email from support@textverified.com, 2026-10-02, ticket 4471",
        "reason": "TextVerified approved resale in writing",
    }, format="json")
    assert granted.status_code == 200, granted.data
    assert granted.data["resale_authorized"] is True and granted.data["selling"] is True
    assert granted.data["authorized_by"] == admin_user.email

    action = AdminAction.objects.get(action="PROVIDER_RESALE_AUTHORIZED")
    assert action.before["resale_authorized"] is False
    assert "ticket 4471" in action.after["authorization_reference"]
    # Customers now see it.
    assert "tiktok" in {r["slug"] for r in api.get(MARKET, {"country": "US"}).data["results"]}


# ---------------------------------------------------------------------------
# Authorised: the purchase flow
# ---------------------------------------------------------------------------


def test_a_usa_purchase_runs_end_to_end(tv, tv_catalog, buyer, auth,
                                        django_capture_on_commit_callbacks):
    authorise(tv_catalog)
    verification_routes(tv)

    response = buy(auth(buyer), django_capture_on_commit_callbacks)
    assert response.status_code == 201, response.data
    order = Order.objects.get(reference=response.data["reference"])

    assert order.provider == tv_catalog
    assert order.provider_order_id == "ver_1"
    assert order.phone_number == "+12025550123"
    assert order.status == OrderStatus.WAITING_FOR_CODE
    # The price snapshot: provider cost, FX and customer price, frozen on the order.
    assert order.provider_cost == Decimal("0.5000") and order.provider_currency == "USD"
    assert Decimal(order.price_breakdown["provider_cost"]) == Decimal("0.5000")
    assert order.price == Decimal(order.price_breakdown["customer_price"])
    debits = WalletLedgerEntry.objects.filter(wallet__user=buyer,
                                              entry_type=LedgerEntryType.PURCHASE)
    assert debits.count() == 1 and debits.get().amount == order.price
    # maxPrice was sent, so a price move cannot bill us more than quoted.
    assert creates(tv)[0]["json"]["maxPrice"] == pytest.approx(0.53)

    verification_routes(tv, state="verificationCompleted", code="482913")
    order = poll_order(order)
    assert order.status == OrderStatus.CODE_RECEIVED
    assert order.verification_code == "482913"


def test_a_double_tap_buys_one_number_and_charges_once(tv, tv_catalog, buyer, auth,
                                                       django_capture_on_commit_callbacks):
    authorise(tv_catalog)
    verification_routes(tv)
    client = auth(buyer)

    first = buy(client, django_capture_on_commit_callbacks, key="tap-tap-1")
    second = buy(client, django_capture_on_commit_callbacks, key="tap-tap-1")

    assert first.data["reference"] == second.data["reference"]
    assert Order.objects.filter(user=buyer).count() == 1
    assert len(creates(tv)) == 1
    # And the provider was given a key, so its own retries cannot double-buy.
    order = Order.objects.get(user=buyer)
    assert creates(tv)[0]["headers"]["Idempotency-Key"] == f"vgh:{order.id}"
    assert WalletLedgerEntry.objects.filter(
        wallet__user=buyer, entry_type=LedgerEntryType.PURCHASE).count() == 1


def test_an_empty_provider_balance_refunds_and_alerts_staff(tv, tv_catalog, buyer, auth,
                                                            admin_user,
                                                            django_capture_on_commit_callbacks):
    authorise(tv_catalog)
    tv["routes"][("POST", "/api/pub/v2/verifications")] = Reply(
        400, {"errorCode": "InsufficientBalance", "errorDescription": "Not enough credit."})

    response = buy(auth(buyer), django_capture_on_commit_callbacks)
    order = Order.objects.get(reference=response.data["reference"])

    assert order.status == OrderStatus.REFUNDED
    assert "balance" not in order.failure_reason.lower()
    assert "credit" not in order.failure_reason.lower()
    wallet = get_or_create_wallet(buyer)
    assert wallet.balance == Decimal("200.00")
    assert verify_wallet_integrity(wallet)["ok"] is True
    alert = ProviderAlert.objects.get(kind=AlertKind.PROVIDER_REFUSED)
    assert "InsufficientBalance" in alert.message


def test_a_provider_timeout_refunds(tv, tv_catalog, buyer, auth,
                                    django_capture_on_commit_callbacks):
    authorise(tv_catalog)

    def timeout(body, params):
        raise requests.Timeout("slow")

    tv["routes"][("POST", "/api/pub/v2/verifications")] = timeout

    response = buy(auth(buyer), django_capture_on_commit_callbacks)

    order = Order.objects.get(reference=response.data["reference"])
    assert order.status == OrderStatus.REFUNDED
    assert get_or_create_wallet(buyer).balance == Decimal("200.00")


def test_canada_is_refused_server_side(tv, tv_catalog, buyer, auth,
                                       django_capture_on_commit_callbacks):
    """TextVerified sells US numbers only, and the marketplace sells the US only."""
    authorise(tv_catalog)
    response = buy(auth(buyer), django_capture_on_commit_callbacks, country="CA")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "UNSUPPORTED_COUNTRY"
    assert creates(tv) == []
    assert [c.code for c in tv_module.TextVerifiedProvider().get_countries()] == ["US"]


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


def test_the_balance_is_read_and_graded(tv, tv_catalog, admin_user,
                                        django_capture_on_commit_callbacks):
    tv["routes"][("GET", "/api/pub/v2/account/me")] = Reply(
        200, {"username": "ops@verifygh.test", "currentBalance": 3.5})
    with django_capture_on_commit_callbacks(execute=True):
        account = funding.sync_balance(tv_catalog)

    assert account.available == Decimal("3.5000") and account.frozen == Decimal("0.0000")
    assert account.status == BalanceStatus.LOW
    assert ProviderAlert.objects.filter(kind=AlertKind.LOW_BALANCE).exists()


def test_missing_credentials_are_reported_not_alerted(settings, exchange_rate, admin_user):
    settings.PROVIDER_CREDENTIALS = {**settings.PROVIDER_CREDENTIALS,
                                     "textverified": {"api_key": "", "api_username": "",
                                                      "base_url": ""}}
    provider = Provider.objects.create(adapter_key="textverified", name="TextVerified")
    account = funding.sync_balance(provider)

    assert account.status == BalanceStatus.UNKNOWN
    assert "Not configured" in account.last_sync_error
    assert account.consecutive_sync_failures == 0
    assert not ProviderAlert.objects.exists()


# ---------------------------------------------------------------------------
# Catalogue sync pacing
# ---------------------------------------------------------------------------


def test_the_sync_resumes_where_a_rate_limit_stopped_it(tv, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "PROVIDER_CATALOG_LIMIT": 0}
    names = [f"svc{i}" for i in range(5)]
    tv["routes"][("GET", "/api/pub/v2/services")] = Reply(
        200, [{"serviceName": n, "capability": "sms"} for n in names]
        + [{"serviceName": "voiceonly", "capability": "voice"}])
    priced: list[str] = []

    def pricing(body, params):
        if len(priced) == 2:
            return Reply(429, {})
        priced.append(body["serviceName"])
        return Reply(200, {"serviceName": body["serviceName"], "price": 0.3})

    tv["routes"][("POST", "/api/pub/v2/pricing/verifications")] = pricing
    adapter = tv_module.TextVerifiedProvider()

    first = adapter.get_services()
    assert [s.code for s in first] == ["svc0", "svc1"]

    tv["routes"][("POST", "/api/pub/v2/pricing/verifications")] = (
        lambda body, params: Reply(200, {"serviceName": body["serviceName"], "price": 0.3}))
    second = adapter.get_services()
    # Limit 0 is "no count limit"; it resumed at svc2, and the voice-only
    # service is never priced (we sell SMS verifications).
    assert [s.code for s in second] == ["svc2", "svc3", "svc4", "svc0", "svc1"]
    assert all(c["json"]["serviceName"] != "voiceonly" for c in tv["calls"]
               if c["path"] == "/api/pub/v2/pricing/verifications")


# ---------------------------------------------------------------------------
# Webhooks: a signed prompt to poll, nothing more
# ---------------------------------------------------------------------------


def sign(body: bytes, secret: str = SECRET) -> str:
    return "HMAC-SHA512=" + base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha512).digest()).decode()


@pytest.fixture
def polled(monkeypatch):
    from apps.orders import tasks

    seen: list[str] = []
    monkeypatch.setattr(tasks.poll_order_task, "delay", lambda order_id: seen.append(order_id))
    return seen


def _active_order(provider, user, vid="ver_77"):
    from apps.catalog.models import Service

    offering = ProviderService.objects.filter(provider=provider).select_related(
        "service", "country").first()
    return Order.objects.create(
        user=user, reference="VG-TVWH-00001", service=offering.service or Service.objects.first(),
        country=offering.country, provider=provider, price=Decimal("8.00"),
        provider_cost=Decimal("0.50"), currency="GHS", idempotency_key="tv-webhook-1",
        status=OrderStatus.WAITING_FOR_CODE, provider_order_id=vid,
    )


def test_a_signed_sms_webhook_prompts_a_poll(tv, tv_catalog, user, api, polled):
    order = _active_order(tv_catalog, user)
    body = json.dumps({"event": "v2.sms.received", "id": "evt_1", "attempt": 1,
                       "data": {"reservationId": "ver_77", "parsedCode": "999999"}}).encode()

    response = api.post(WEBHOOK, data=body, content_type="application/json",
                        HTTP_X_WEBHOOK_SIGNATURE=sign(body))

    assert response.status_code == 200
    assert polled == [str(order.id)]
    # The code in the callback is never used: only the authenticated poll sets one.
    order.refresh_from_db()
    assert order.verification_code == ""


def test_a_forged_or_tampered_webhook_is_rejected(tv, tv_catalog, user, api, polled):
    _active_order(tv_catalog, user)
    body = json.dumps({"event": "v2.sms.received", "data": {"reservationId": "ver_77"}}).encode()

    forged = api.post(WEBHOOK, data=body, content_type="application/json",
                      HTTP_X_WEBHOOK_SIGNATURE=sign(body, "whsec_not-our-secret"))
    tampered = api.post(WEBHOOK, data=body + b" ", content_type="application/json",
                        HTTP_X_WEBHOOK_SIGNATURE=sign(body))
    unsigned = api.post(WEBHOOK, data=body, content_type="application/json")

    assert (forged.status_code, tampered.status_code, unsigned.status_code) == (401, 401, 401)
    assert polled == []


def test_without_a_webhook_secret_the_endpoint_is_absent(tv, settings, api, polled):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "textverified": {**settings.PROVIDER_CREDENTIALS["textverified"], "webhook_secret": ""},
    }
    body = b'{"event":"v2.sms.received","data":{"reservationId":"ver_77"}}'
    response = api.post(WEBHOOK, data=body, content_type="application/json",
                        HTTP_X_WEBHOOK_SIGNATURE=sign(body))
    assert response.status_code == 404
    assert api.post("/api/v1/verification/webhooks/mock/", data=body,
                    content_type="application/json").status_code == 404


# ---------------------------------------------------------------------------
# OnlineSim switched off, history kept
# ---------------------------------------------------------------------------


def test_switching_onlinesim_off_keeps_its_history_and_stops_calls(auth, admin_user, user, tv,
                                                                   exchange_rate):
    onlinesim = Provider.objects.create(adapter_key="onlinesim", name="Onlinesim",
                                        resale_authorized=True,
                                        authorization_reference="OnlineSim support, 2026-09-27")
    from apps.catalog.models import Country, Service

    old = Order.objects.create(
        user=user, reference="VG-OS-00001", provider=onlinesim, price=Decimal("5.00"),
        service=Service.objects.create(slug="probe", name="Probe"),
        country=Country.objects.create(code="US", name="USA", dial_code="+1"),
        provider_cost=Decimal("0.12"), currency="GHS", idempotency_key="os-history-1",
        status=OrderStatus.COMPLETED, provider_order_id="tz-1",
    )

    response = auth(admin_user, ADMIN_PASSWORD).post(
        f"{PROVIDERS}onlinesim/status/", {"enabled": False, "reason": "TextVerified is primary"},
        format="json")
    assert response.status_code == 200, response.data
    assert response.data["selling"] is False

    # History intact.
    old.refresh_from_db()
    assert old.provider == onlinesim and old.status == OrderStatus.COMPLETED
    assert AdminAction.objects.filter(action="PROVIDER_DISABLED").count() == 1
    # And nothing calls it: the transport fails any unexpected request.
    summary = sync_catalog("onlinesim")
    assert "disabled" in summary["errors"][0]


def test_one_provider_reservation_belongs_to_one_order(tv_catalog, user, other_user):
    from apps.catalog.models import Service

    offering = ProviderService.objects.filter(provider=tv_catalog).first()
    common = {"provider": tv_catalog, "service": offering.service, "country": offering.country,
              "price": Decimal("8.00"), "provider_cost": Decimal("0.5"), "currency": "GHS",
              "provider_order_id": "ver_dup"}
    Order.objects.create(user=user, reference="VG-DUP-1", idempotency_key="d1", **common)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.create(user=other_user, reference="VG-DUP-2", idempotency_key="d2", **common)
    # Orders not yet given a reservation id are not affected.
    blank = {**common, "provider_order_id": ""}
    Order.objects.create(user=user, reference="VG-BLANK-1", idempotency_key="b1", **blank)
    Order.objects.create(user=user, reference="VG-BLANK-2", idempotency_key="b2", **blank)
    assert Service.objects.exists()


# ---------------------------------------------------------------------------
# Admin > Providers reports only what it measured
# ---------------------------------------------------------------------------


def test_the_providers_page_reports_measured_figures(tv, tv_catalog, auth, admin_user):
    data = auth(admin_user, ADMIN_PASSWORD).get(PROVIDERS).data
    row = next(p for p in data["providers"] if p["adapter_key"] == "textverified")

    assert row["configured"] is True
    assert row["resale_authorized"] is False and row["selling"] is False
    assert row["capabilities"] == {"balance": True, "account_funding": False, "webhooks": True,
                                   "webhooks_active": True, "issue_reports": True}
    assert row["catalogue"]["offerings"] == 2 and row["catalogue"]["listed_to_customers"] == 0
    # No orders yet: rates are unknown, not zero and not invented.
    assert row["orders"]["purchase_success_rate"] is None
    assert row["orders"]["sms_success_rate"] is None
    # The sync above went through the budgeted wrapper, so calls were measured.
    assert row["api"]["calls"] >= 1 and row["api"]["last_success_at"]
    assert row["api"]["average_ms"] is not None
