"""The TextVerified rental calls, against responses shaped like the published spec.

No network. Paths, bodies and fields follow the OpenAPI v2 document
(`/pricing/rentals`, `/inventory/rentals`, `/reservations/rental`,
`/sales/{id}`, `/reservations/rental/nonrenewable/{id}`, its `/refund`,
`/reservations/rentals/extensions` and `/sms`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import requests

from apps.common.errors import ProviderError
from apps.verification.base import RentalState
from apps.verification.textverified import TextVerifiedProvider

pytestmark = pytest.mark.django_db

BASE = "https://www.textverified.com"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = b"" if payload is None else b'{"x":1}'

    def json(self):
        return self._payload


@pytest.fixture
def tv(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "textverified": {"api_key": "test-key", "api_username": "ops@verifygh.test",
                         "base_url": BASE},
    }
    return TextVerifiedProvider()


@pytest.fixture
def transport(monkeypatch):
    calls: list[dict] = []
    routes: dict[tuple[str, str], object] = {
        ("POST", "/api/pub/v2/auth"): FakeResponse(200, {"token": "tok", "expiresIn": 3600}),
    }

    def fake_request(self, method, url, headers=None, json=None, params=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers or {}, "json": json,
                      "params": params})
        handler = routes.get((method, url.replace(BASE, "").split("?")[0]))
        if handler is None:
            raise AssertionError(f"unexpected call: {method} {url}")
        return handler(json, params) if callable(handler) else handler

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return {"calls": calls, "routes": routes}


RENTAL = {
    "id": "rnt_1", "number": "2025550123", "createdAt": "2026-10-14T10:00:00Z",
    "endsAt": "2026-11-13T10:00:00Z", "serviceName": "whatsapp",
    "state": "nonrenewableActive", "saleId": "sale_1", "alwaysOn": True,
    "refund": {"canRefund": True, "refundableUntil": "2026-10-14T10:20:00Z",
               "link": {"method": "POST", "href": "/x"}},
    "sms": {"method": "GET", "href": "/api/pub/v2/sms?reservationId=rnt_1"},
    "calls": {"method": "GET", "href": "/x"}, "sale": {"method": "GET", "href": "/x"},
}


def test_the_price_check_sends_the_documented_body(tv, transport):
    transport["routes"][("POST", "/api/pub/v2/pricing/rentals")] = FakeResponse(
        200, {"serviceName": "whatsapp", "price": 4.8})

    assert tv.rental_price("whatsapp", 30) == Decimal("4.8")
    body = transport["calls"][-1]["json"]
    assert body == {"serviceName": "whatsapp", "areaCode": False, "numberType": "mobile",
                    "capability": "sms", "isRenewable": False, "duration": "thirtyDay"}


def test_an_unsupported_combination_is_not_sold_rather_than_an_error(tv, transport):
    transport["routes"][("POST", "/api/pub/v2/pricing/rentals")] = FakeResponse(
        400, {"errorCode": "BadRequest", "errorDescription": "Unsupported"})
    assert tv.rental_price("allservices", 1) is None


def test_an_unknown_length_is_never_sent(tv, transport):
    with pytest.raises(ValueError):
        tv.rental_price("whatsapp", 2)


def test_renting_follows_the_sale_to_the_rental_with_an_idempotency_key(tv, transport):
    transport["routes"][("POST", "/api/pub/v2/reservations/rental")] = FakeResponse(
        201, {"method": "GET", "href": "/api/pub/v2/sales/sale_1"})
    transport["routes"][("GET", "/api/pub/v2/sales/sale_1")] = FakeResponse(200, {
        "id": "sale_1", "state": "succeeded", "total": 4.8, "backOrderReservations": [],
        "createdAt": "2026-10-14T10:00:00Z", "updatedAt": "2026-10-14T10:00:00Z",
        "reservations": [{"id": "rnt_1", "reservationType": "nonrenewable",
                          "serviceName": "whatsapp",
                          "link": {"method": "GET",
                                   "href": "/api/pub/v2/reservations/rental/nonrenewable/rnt_1"}}],
    })
    transport["routes"][("GET", "/api/pub/v2/reservations/rental/nonrenewable/rnt_1")] = \
        FakeResponse(200, RENTAL)

    dto = tv.create_rental("whatsapp", 30, idempotency_key="vgh-rental:abc")

    create = next(c for c in transport["calls"] if c["url"].endswith("/reservations/rental"))
    assert create["headers"]["Idempotency-Key"] == "vgh-rental:abc"
    assert create["json"] == {"allowBackOrderReservations": False, "isRenewable": False,
                              "duration": "thirtyDay", "numberType": "mobile",
                              "serviceName": "whatsapp", "capability": "sms"}
    assert dto.state == RentalState.ACTIVE
    assert dto.provider_rental_id == "rnt_1" and dto.sale_id == "sale_1"
    assert dto.phone_number == "+12025550123"
    assert dto.cost == Decimal("4.8")
    assert dto.can_refund is True and dto.refundable_until is not None


def test_a_sale_still_processing_is_pending(tv, transport):
    transport["routes"][("GET", "/api/pub/v2/sales/sale_2")] = FakeResponse(200, {
        "id": "sale_2", "state": "processing", "total": 4.8, "reservations": [],
        "backOrderReservations": []})
    dto = tv.get_rental_sale("sale_2")
    assert dto.state == RentalState.PENDING and dto.sale_id == "sale_2"


def test_a_failed_sale_is_failed(tv, transport):
    transport["routes"][("GET", "/api/pub/v2/sales/sale_3")] = FakeResponse(200, {
        "id": "sale_3", "state": "failed", "total": 0, "reservations": [],
        "backOrderReservations": []})
    assert tv.get_rental_sale("sale_3").state == RentalState.FAILED


def test_a_purchase_still_running_is_raised_as_unclear_not_refused(tv, transport):
    from apps.rentals.services import _is_refusal

    transport["routes"][("POST", "/api/pub/v2/reservations/rental")] = FakeResponse(
        409, {"errorCode": "IdempotencyConflict", "errorDescription": "In progress"})
    with pytest.raises(ProviderError) as caught:
        tv.create_rental("whatsapp", 30, idempotency_key="k")
    assert caught.value.http_status == 409
    assert _is_refusal(caught.value) is False


def test_a_refused_purchase_is_a_refusal(tv, transport):
    from apps.rentals.services import _is_refusal

    transport["routes"][("POST", "/api/pub/v2/reservations/rental")] = FakeResponse(
        400, {"errorCode": "Unavailable", "errorDescription": "No stock"})
    with pytest.raises(ProviderError) as caught:
        tv.create_rental("whatsapp", 30, idempotency_key="k")
    assert _is_refusal(caught.value) is True


def test_a_timeout_is_unclear(tv, transport, monkeypatch):
    from apps.rentals.services import _is_refusal

    def timeout(*args, **kwargs):
        raise requests.Timeout()

    transport["routes"][("POST", "/api/pub/v2/reservations/rental")] = timeout
    with pytest.raises(ProviderError) as caught:
        tv.create_rental("whatsapp", 30, idempotency_key="k")
    assert _is_refusal(caught.value) is False


def test_the_refund_call_reports_a_refusal_as_false(tv, transport):
    path = "/api/pub/v2/reservations/rental/nonrenewable/rnt_1/refund"
    transport["routes"][("POST", path)] = FakeResponse(400, {"errorCode": "BadRequest",
                                                             "errorDescription": "No"})
    assert tv.refund_rental("rnt_1") is False
    transport["routes"][("POST", path)] = FakeResponse(200)
    assert tv.refund_rental("rnt_1") is True


def test_an_extension_reports_the_new_end_and_cost(tv, transport):
    transport["routes"][("POST", "/api/pub/v2/reservations/rentals/extensions")] = FakeResponse(
        200, {"reservationId": "rnt_1", "extensionAmount": "sevenDay", "cost": 3.0,
              "createdAt": "2026-10-14T10:00:00Z", "originalEndsAt": "2026-11-13T10:00:00Z",
              "newEndsAt": "2026-11-20T10:00:00Z", "id": "ext_1"})
    dto = tv.extend_rental("rnt_1", 7)
    assert transport["calls"][-1]["json"] == {"rentalId": "rnt_1",
                                              "extensionDuration": "sevenDay"}
    assert dto.provider_extension_id == "ext_1" and dto.cost == Decimal("3.0")
    assert dto.new_ends_at.isoformat().startswith("2026-11-20")


def test_messages_follow_the_next_page_link(tv, transport):
    def sms(body, params):
        return FakeResponse(200, {
            "data": [{"id": "s1", "from": "22395", "to": "2025550123",
                      "createdAt": "2026-10-14T10:05:00Z",
                      "smsContent": "Your code is 708 609", "parsedCode": "708 609 ",
                      "encrypted": False}],
            "hasNext": True, "hasPrevious": False, "count": 2,
            "links": {"next": {"method": "GET", "href": "/api/pub/v2/sms-page2"},
                      "current": {"method": "GET", "href": "/x"}, "previous": None},
        })

    transport["routes"][("GET", "/api/pub/v2/sms")] = sms
    transport["routes"][("GET", "/api/pub/v2/sms-page2")] = FakeResponse(200, {
        "data": [{"id": "s2", "from": "1", "to": "2", "createdAt": "2026-10-14T10:01:00Z",
                  "smsContent": "Hello", "parsedCode": "", "encrypted": False}],
        "hasNext": False, "hasPrevious": True, "count": 2, "links": {"next": None},
    })

    messages = tv.rental_messages("rnt_1")

    assert [m.provider_message_id for m in messages] == ["s1", "s2"]
    assert messages[0].code == "708609"
    assert transport["calls"][1]["params"] == {"reservationId": "rnt_1"}


def test_rental_states_map_and_unknown_ones_are_not_acted_on(tv, transport):
    path = "/api/pub/v2/reservations/rental/nonrenewable/rnt_1"
    transport["routes"][("GET", path)] = FakeResponse(200, {**RENTAL,
                                                            "state": "nonrenewableExpired"})
    assert tv.get_rental("rnt_1").state == RentalState.EXPIRED
    transport["routes"][("GET", path)] = FakeResponse(200, {**RENTAL, "state": "somethingNew"})
    assert tv.get_rental("rnt_1").state == RentalState.UNKNOWN


def test_a_sale_whose_reservation_link_points_at_another_link_is_followed(tv, transport):
    """The real shape (VGH-RNT-52BTF4): a sale's reservation link points at
    `GET /reservations/{id}`, which answers with the link to the rental."""
    transport["routes"][("POST", "/api/pub/v2/reservations/rental")] = FakeResponse(
        201, {"method": "GET", "href": "/api/pub/v2/sales/sale_9"})
    transport["routes"][("GET", "/api/pub/v2/sales/sale_9")] = FakeResponse(200, {
        "id": "sale_9", "state": "succeeded", "total": 6.0, "backOrderReservations": [],
        "createdAt": "2026-10-16T01:18:41Z", "updatedAt": "2026-10-16T01:18:41Z",
        "reservations": [{"id": "lr_9", "reservationType": "nonrenewable",
                          "serviceName": "All",
                          "link": {"method": "GET",
                                   "href": "/api/pub/v2/reservations/lr_9?type=Nonrenewable"}}],
    })
    # The documented Link answer: another link, not the rental.
    transport["routes"][("GET", "/api/pub/v2/reservations/lr_9")] = FakeResponse(
        200, {"method": "GET", "href": "/api/pub/v2/reservations/rental/nonrenewable/lr_9"})
    transport["routes"][("GET", "/api/pub/v2/reservations/rental/nonrenewable/lr_9")] = \
        FakeResponse(200, {**RENTAL, "id": "lr_9", "serviceName": "All",
                           "state": "nonrenewableActive", "saleId": "sale_9"})

    dto = tv.create_rental("allservices", 3, idempotency_key="vgh-rental:abc")

    assert dto.state == RentalState.ACTIVE
    assert dto.provider_rental_id == "lr_9"
    assert dto.phone_number == "+12025550123"
    assert dto.cost == Decimal("6.0")


def test_a_link_loop_is_not_followed_for_ever(tv, transport):
    transport["routes"][("GET", "/api/pub/v2/sales/loop")] = FakeResponse(200, {
        "id": "loop", "state": "succeeded", "total": 1.0, "backOrderReservations": [],
        "reservations": [{"id": "lr_x", "reservationType": "nonrenewable",
                          "serviceName": "All",
                          "link": {"method": "GET", "href": "/api/pub/v2/round"}}],
    })
    transport["routes"][("GET", "/api/pub/v2/round")] = FakeResponse(
        200, {"method": "GET", "href": "/api/pub/v2/round"})

    dto = tv.get_rental_sale("loop")

    # Unknown, never mistaken for a rental we can hand over.
    assert dto.provider_rental_id == ""
    assert len([c for c in transport["calls"] if c["url"].endswith("/round")]) <= 3
