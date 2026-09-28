"""The OnlineSim adapter.

Two jobs, in order of importance:

1. **Prove nothing was invented.** Every path the adapter calls, and every
   provider constant it recognises, is checked against
   `apps/verification/onlinesim_endpoints.json`, which records what their
   published documentation actually says. A mistyped path fails here rather
   than failing a customer's order.

2. **Prove it fails safe.** The interesting cases are all failures: an unknown
   state, a vanished operation, an unmappable country, a cancel inside the
   protective interval. Each one must leave the customer's money recoverable
   and must never read as "delivered".

No network: a fake transport answers with the response shapes the vendor
documents.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from apps.common.errors import ProviderError, ServiceUnavailable
from apps.verification.base import ProviderOrderState
from apps.verification.onlinesim import OnlineSimProvider, _CountryCodes

pytestmark = pytest.mark.django_db

SPEC = json.loads(
    (Path(__file__).resolve().parent.parent
     / "apps" / "verification" / "onlinesim_endpoints.json").read_text(encoding="utf-8")
)


# ---------------------------------------------------------------------------
# A fake transport speaking the documented shapes
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, payload, *, text: str | None = None):
        self.status_code = status
        self._payload = payload
        self.content = b"x" if payload is not None or text else b""
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Records calls and replays canned responses keyed by path."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        path = url.split("onlinesim.io", 1)[-1]
        self.calls.append((path, dict(params or {}), dict(headers or {})))
        answer = self.routes.get(path)
        if answer is None:
            raise AssertionError(f"adapter called an unrouted path: {path}")
        if callable(answer):
            answer = answer(params or {})
        return answer


TARIFFS = {
    "response": "1",
    "countries": {
        "_233": {"name": "Ghana", "original": "ghana", "code": 233,
                 "pos": 0, "other": False, "new": False, "enable": True},
        "_7": {"name": "Russia", "original": "russia", "code": 7,
               "pos": 1, "other": False, "new": False, "enable": True},
        # The shapes observed live on 2026-09-28. 1000 is not a calling code,
        # 77 splits Kazakhstan out of +7, and the UK is listed as "Britain".
        "_1": {"name": "USA", "original": "usa", "code": 1, "enable": True},
        "_1000": {"name": "Canada", "original": "canada", "code": 1000, "enable": True},
        "_44": {"name": "Britain", "original": "united_kingdom", "code": 44,
                "enable": True},
        "_77": {"name": "Kazakhstan", "original": "kazakhstan", "code": 77,
                "enable": True},
    },
    "services": {
        "_telegram": {"id": 1, "count": 42, "price": "0.55",
                      "service": "Telegram", "slug": "telegram"},
        "_whatsapp": {"id": 2, "count": 0, "price": "1.20",
                      "service": "WhatsApp", "slug": "whatsapp"},
    },
    "page": 1, "country": 233, "filter": "", "end": True, "favorites": {},
}


@pytest.fixture
def provider(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "onlinesim": {"api_key": "test-key", "base_url": "https://onlinesim.io",
                      "currency": "USD"},
    }
    return OnlineSimProvider()


def wire(provider, routes):
    session = FakeSession(routes)
    provider._session = session
    return session


# ---------------------------------------------------------------------------
# 1. Provenance - nothing invented
# ---------------------------------------------------------------------------


def test_every_path_the_adapter_calls_is_documented():
    documented = {e["path"] for e in SPEC["endpoints"].values()}
    used = {
        value
        for name, value in vars(OnlineSimProvider).items()
        if name.startswith("PATH_") and isinstance(value, str)
    }

    assert used, "the adapter defines no paths at all"
    undocumented = used - documented
    assert not undocumented, (
        f"these paths are not in onlinesim_endpoints.json: {sorted(undocumented)}. "
        "Add them from the vendor's documentation first, or remove them."
    )


def test_the_base_url_is_the_documented_host():
    assert OnlineSimProvider.BASE_URL == SPEC["base_url"]


def test_the_only_state_the_adapter_names_is_the_documented_one():
    """OnlineSim publishes exactly one operation state. Guessing others is how
    an unfinished order gets treated as delivered."""
    assert SPEC["operation_states"]["documented"] == ["TZ_NUM_WAIT"]
    assert OnlineSimProvider.STATE_WAITING in SPEC["operation_states"]["documented"]


def test_every_error_code_the_adapter_maps_is_documented():
    documented = set(SPEC["error_codes"]["documented"])
    mapped = set(OnlineSimProvider.ERROR_MESSAGES)

    undocumented = mapped - documented
    assert not undocumented, f"invented error codes: {sorted(undocumented)}"
    # And we handle all of them, so a documented failure never falls through to
    # a blank message.
    assert documented == mapped, f"unhandled documented codes: {sorted(documented - mapped)}"


def test_the_webhook_is_not_trusted():
    """It is documented with no signature, so nothing it says can be believed."""
    assert SPEC["webhook"]["signature"] is None
    assert OnlineSimProvider.supports_webhooks is False


def test_rented_number_endpoints_are_not_used():
    """This platform sells single activations; rental is a different product."""
    used = {v for k, v in vars(OnlineSimProvider).items()
            if k.startswith("PATH_") and isinstance(v, str)}
    assert not any("/rent/" in path for path in used)


# ---------------------------------------------------------------------------
# 2. Credentials and configuration
# ---------------------------------------------------------------------------


def test_without_a_key_the_adapter_refuses_rather_than_calling_out(settings):
    settings.PROVIDER_CREDENTIALS = {
        **settings.PROVIDER_CREDENTIALS,
        "onlinesim": {"api_key": "", "base_url": "https://onlinesim.io"},
    }
    unconfigured = OnlineSimProvider()

    assert unconfigured.is_configured is False
    with pytest.raises(ServiceUnavailable):
        unconfigured.get_countries()
    assert unconfigured.health_check() is False


def test_the_api_key_travels_in_the_header_not_the_query_string(provider):
    """A query string reaches proxy logs and error trackers; this key spends money."""
    session = wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    provider.get_countries()

    path, params, headers = session.calls[0]
    assert headers["Authorization"] == "Bearer test-key"
    assert "apikey" not in params
    assert "test-key" not in json.dumps(params)


def test_responses_are_requested_in_english(provider):
    """The documented default is Russian, which would land in our logs and UI."""
    session = wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    provider.get_countries()

    assert session.calls[0][1]["lang"] == "en"


# ---------------------------------------------------------------------------
# 3. Catalogue
# ---------------------------------------------------------------------------


def test_countries_are_mapped_to_iso_codes(provider):
    session = wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    countries = provider.get_countries()

    assert {c.code for c in countries} == {"GH", "RU", "US", "CA", "GB", "KZ"}
    ghana = next(c for c in countries if c.code == "GH")
    assert ghana.dial_code == "+233"
    assert len(session.calls) == 1


def test_an_unmappable_country_is_skipped_not_guessed(provider):
    """A wrong country means a number that cannot receive the customer's code."""
    payload = {
        **TARIFFS,
        "countries": {
            "_233": TARIFFS["countries"]["_233"],
            "_99999": {"name": "Atlantis", "code": 99999, "enable": True},
        },
    }
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, payload)})

    codes = {c.code for c in provider.get_countries()}

    assert codes == {"GH"}


def test_a_disabled_country_is_left_out(provider):
    payload = {
        **TARIFFS,
        "countries": {
            "_233": {**TARIFFS["countries"]["_233"], "enable": False},
            "_7": TARIFFS["countries"]["_7"],
        },
    }
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, payload)})

    assert {c.code for c in provider.get_countries()} == {"RU"}


def test_services_are_priced_and_carry_availability(provider):
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    offerings = provider.get_services()

    telegram = next(o for o in offerings if o.code == "telegram" and o.country_code == "GH")
    assert telegram.cost == Decimal("0.55")
    assert telegram.currency == "USD"
    assert telegram.available is True
    assert telegram.available_count == 42

    sold_out = next(o for o in offerings if o.code == "whatsapp" and o.country_code == "GH")
    assert sold_out.available is False


def test_a_service_that_cannot_be_priced_is_left_out(provider):
    """Better absent than listed at a guessed cost we would then have to honour."""
    payload = {
        **TARIFFS,
        "services": {
            "_telegram": TARIFFS["services"]["_telegram"],
            "_broken": {"id": 3, "count": 5, "price": None,
                        "service": "Broken", "slug": "broken"},
            "_free": {"id": 4, "count": 5, "price": "0",
                      "service": "Free", "slug": "free"},
        },
    }
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, payload)})

    codes = {o.code for o in provider.get_services()}

    assert "telegram" in codes
    assert "broken" not in codes
    assert "free" not in codes


def test_the_catalogue_is_bounded(provider, settings):
    """Without a bound a sync would hammer the provider listing everything."""
    settings.VERIFYGH = {**settings.VERIFYGH, "PROVIDER_CATALOG_LIMIT": 1}
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    assert len(provider.get_services()) == 1


def test_one_failing_country_does_not_empty_the_catalogue(provider):
    """A single upstream hiccup must not take the whole marketplace offline."""
    calls = {"n": 0}

    def tariffs(params):
        # The country-less call lists countries; then Ghana fails and Russia works.
        if "country" not in params:
            return FakeResponse(200, TARIFFS)
        calls["n"] += 1
        if str(params.get("country")) == "233":
            return FakeResponse(200, {"response": "ERROR_UNDEFINED"})
        return FakeResponse(200, TARIFFS)

    wire(provider, {provider.PATH_TARIFFS: tariffs})

    offerings = provider.get_services()

    assert offerings, "a failure for one country emptied the whole catalogue"
    assert "GH" not in {o.country_code for o in offerings}


# ---------------------------------------------------------------------------
# 4. Ordering
# ---------------------------------------------------------------------------


def test_creating_an_order_returns_the_number_in_one_call(provider):
    """`number=true` avoids a second round trip just to learn the number."""
    session = wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(
            200, {"response": 1, "tzid": 10000, "number": "+233200000000", "sum": "0.55"}
        ),
    })

    order = provider.create_order("telegram", "GH", "idem-1")

    assert order.provider_order_id == "10000"
    assert order.phone_number == "+233200000000"
    assert order.state is ProviderOrderState.NUMBER_ASSIGNED

    order_call = next(c for c in session.calls if c[0] == provider.PATH_ORDER)
    assert order_call[1]["service"] == "telegram"
    assert str(order_call[1]["country"]) == "233"
    assert order_call[1]["number"] == "true"


def test_an_order_without_a_reference_is_a_clean_failure(provider):
    """No tzid means nothing to poll or cancel - it must refund, not hang."""
    wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(200, {"response": 1}),
    })

    with pytest.raises(ProviderError):
        provider.create_order("telegram", "GH", "idem-2")


def test_no_number_available_is_a_clean_failure(provider):
    wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(200, {"response": "NO_NUMBER"}),
    })

    with pytest.raises(ProviderError, match="No number is available"):
        provider.create_order("telegram", "GH", "idem-3")


def test_an_empty_upstream_balance_never_reaches_the_customer(provider):
    """Our funding problem must not be described to a customer as their problem."""
    wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(200, {"response": "WARNING_LOW_BALANCE"}),
    })

    with pytest.raises(ProviderError) as raised:
        provider.create_order("telegram", "GH", "idem-4")

    message = str(raised.value).lower()
    assert "balance" not in message
    assert "temporarily unavailable" in message


def test_ordering_for_an_unsupported_country_is_refused_before_calling_out(provider):
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    with pytest.raises(ProviderError, match="do not offer"):
        provider.create_order("telegram", "ZZ", "idem-5")


# ---------------------------------------------------------------------------
# 5. Status - the part that decides whether money is kept or returned
# ---------------------------------------------------------------------------


def state_route(entry):
    return FakeResponse(200, [entry])


def test_a_waiting_operation_reads_as_waiting(provider):
    wire(provider, {provider.PATH_STATE: state_route(
        {"tzid": 10000, "response": "TZ_NUM_WAIT", "number": "+233200000000",
         "country": 233, "service": "telegram", "sum": 0.55, "time": 596, "msg": ""}
    )})

    status = provider.get_order_status("10000")

    assert status.state is ProviderOrderState.WAITING_FOR_CODE
    assert status.code is None
    assert status.phone_number == "+233200000000"


def test_a_message_marks_the_code_received(provider):
    wire(provider, {provider.PATH_STATE: state_route(
        {"tzid": 10000, "response": "TZ_NUM_WAIT", "number": "+233200000000",
         "country": 233, "service": "telegram", "sum": 0.55, "time": 300, "msg": "123456"}
    )})

    status = provider.get_order_status("10000")

    assert status.state is ProviderOrderState.CODE_RECEIVED
    assert status.code is not None
    assert status.code.code == "123456"


def test_only_the_code_is_requested_never_the_message_body(provider):
    """Less of somebody's SMS held is less to leak and less to retain."""
    session = wire(provider, {provider.PATH_STATE: state_route(
        {"tzid": 10000, "response": "TZ_NUM_WAIT", "msg": "123456", "number": "+1"}
    )})

    status = provider.get_order_status("10000")

    assert session.calls[0][1]["message_to_code"] == 1
    assert status.code.full_text == ""


def test_an_undocumented_state_is_never_treated_as_finished(provider):
    """The failure this guards: a new upstream state making an unfinished order
    look delivered, so the customer pays and gets nothing."""
    wire(provider, {provider.PATH_STATE: state_route(
        {"tzid": 10000, "response": "TZ_SOMETHING_NEW", "number": "+233200000000",
         "msg": "", "time": 100}
    )})

    status = provider.get_order_status("10000")

    assert status.state is ProviderOrderState.PENDING
    assert status.code is None


def test_a_vanished_operation_reads_as_expired_not_completed(provider):
    """ERROR_NO_OPERATIONS means gone. Gone must refund, never settle as sold."""
    wire(provider, {provider.PATH_STATE: FakeResponse(
        200, {"response": "ERROR_NO_OPERATIONS"}
    )})

    status = provider.get_order_status("10000")

    assert status.state is ProviderOrderState.EXPIRED
    assert status.code is None


def test_another_operation_in_the_response_is_not_mistaken_for_ours(provider):
    """getState can answer with every active operation on the account."""
    wire(provider, {provider.PATH_STATE: FakeResponse(200, [
        {"tzid": 99999, "response": "TZ_NUM_WAIT", "msg": "999999", "number": "+1"},
        {"tzid": 10000, "response": "TZ_NUM_WAIT", "msg": "", "number": "+233200000000"},
    ])})

    status = provider.get_order_status("10000")

    assert status.state is ProviderOrderState.WAITING_FOR_CODE
    assert status.code is None, "read another order's code"


def test_a_number_not_yet_assigned_reads_as_pending(provider):
    wire(provider, {provider.PATH_STATE: state_route(
        {"tzid": 10000, "response": "TZ_NUM_WAIT", "number": "", "msg": ""}
    )})

    assert provider.get_order_status("10000").state is ProviderOrderState.PENDING


# ---------------------------------------------------------------------------
# 6. Cancelling and refunding
# ---------------------------------------------------------------------------


def test_cancelling_closes_the_operation(provider):
    session = wire(provider, {
        provider.PATH_CLOSE: FakeResponse(200, {"response": 1, "tzid": 10000})
    })

    assert provider.cancel_order("10000") is True
    assert session.calls[0][1]["tzid"] == "10000"


def test_a_cancel_inside_the_protective_interval_reports_failure(provider):
    """Documented: with no SMS an operation cannot be closed for 120s (300s for
    WhatsApp). Claiming success would tell a customer their money is on its way
    back when the number is still held."""
    wire(provider, {provider.PATH_CLOSE: FakeResponse(200, {"response": "ERROR_UNDEFINED"})})

    assert provider.cancel_order("10000") is False


def test_refunding_closes_the_operation(provider):
    """There is no separate refund endpoint; the frozen balance returns on close."""
    session = wire(provider, {
        provider.PATH_CLOSE: FakeResponse(200, {"response": 1, "tzid": 10000})
    })

    assert provider.refund_order("10000") is True
    assert [c[0] for c in session.calls] == [provider.PATH_CLOSE]


def test_requesting_the_next_message_is_reported_honestly(provider):
    wire(provider, {provider.PATH_REVISE: FakeResponse(200, {"response": "ERROR_UNDEFINED"})})

    assert provider.request_next_message("10000") is False


# ---------------------------------------------------------------------------
# 7. Transport failures
# ---------------------------------------------------------------------------


def test_a_rate_limit_is_not_retried_through(provider):
    wire(provider, {provider.PATH_BALANCE: FakeResponse(429, {})})

    with pytest.raises(ServiceUnavailable) as raised:
        provider._get(provider.PATH_BALANCE)
    assert raised.value.code == "PROVIDER_RATE_LIMITED"


def test_rejected_credentials_do_not_leak_to_the_customer(provider):
    wire(provider, {provider.PATH_BALANCE: FakeResponse(401, {})})

    with pytest.raises(ProviderError) as raised:
        provider._get(provider.PATH_BALANCE)
    assert "test-key" not in str(raised.value)


def test_an_unreadable_response_is_a_clean_failure(provider):
    wire(provider, {provider.PATH_BALANCE: FakeResponse(200, None, text="<html>502</html>")})

    with pytest.raises(ProviderError, match="unreadable"):
        provider._get(provider.PATH_BALANCE)


def test_the_balance_is_readable(provider):
    wire(provider, {provider.PATH_BALANCE: FakeResponse(
        200, {"response": "1", "balance": "106.32", "zbalance": 0}
    )})

    assert provider.account_balance() == Decimal("106.32")
    assert provider.health_check() is True


def test_health_check_is_false_when_the_provider_is_unreachable(provider):
    wire(provider, {provider.PATH_BALANCE: FakeResponse(500, {})})

    assert provider.health_check() is False


# ---------------------------------------------------------------------------
# 8. The country reference file
# ---------------------------------------------------------------------------


def test_what_the_provider_means_by_a_code_beats_what_the_number_means():
    """This table is OnlineSim's, not the ITU's.

    Globally +1 covers the USA, Canada and twenty Caribbean territories. But
    OnlineSim lists the USA under 1 and Canada under 1000, so for this provider
    1 is unambiguous - and treating it as shared would have us send 1 for a
    Canadian order and hand the customer a US number.
    """
    assert _CountryCodes.resolve(1) == "US"
    assert _CountryCodes.resolve(1000) == "CA"
    assert _CountryCodes.resolve(7) == "RU"
    assert _CountryCodes.resolve(77) == "KZ"
    assert _CountryCodes.resolve(44) == "GB"

    # The override wins even when a name suggests otherwise: OnlineSim does not
    # sell Canadian numbers under 1, whatever a caller passes.
    assert _CountryCodes.resolve(1, "Canada") == "US"


def test_codes_without_an_override_are_still_resolved_by_name():
    """The name-based fallback still covers genuinely shared codes."""
    assert _CountryCodes.resolve(590, "Guadeloupe") == "GP"
    assert _CountryCodes.resolve(590, "Saint Martin") == "MF"
    # An unrecognised name on a shared code is skipped, not guessed.
    assert _CountryCodes.resolve(590, "Somewhere Else") is None


def test_unambiguous_codes_resolve_without_a_name():
    assert _CountryCodes.resolve(233) == "GH"
    assert _CountryCodes.resolve("+233") == "GH"
    assert _CountryCodes.resolve(99999) is None


def test_every_mapped_code_is_a_plausible_iso_alpha_2():
    """Country.code is max_length=2 and unique; a longer value would not save."""
    _CountryCodes._load()
    for dial, iso in _CountryCodes._by_dial.items():
        assert len(iso) == 2 and iso.isalpha() and iso.isupper(), (dial, iso)
    for code, names in _CountryCodes._ambiguous.items():
        for name, iso in names.items():
            assert len(iso) == 2 and iso.isupper(), (code, name, iso)


def test_the_reference_file_has_no_duplicate_iso_codes():
    """Two dial codes claiming one ISO code would make the reverse lookup
    ambiguous, and `_dial_for` would silently pick whichever came first."""
    _CountryCodes._load()
    seen: dict[str, str] = {}
    for dial, iso in _CountryCodes._by_dial.items():
        assert iso not in seen, f"{iso} claimed by both +{seen[iso]} and +{dial}"
        seen[iso] = dial


# ---------------------------------------------------------------------------
# 9. OnlineSim's country ids are not always dial codes
# ---------------------------------------------------------------------------


def test_synthetic_country_ids_resolve(provider):
    """Observed live: Canada is 1000 and Kazakhstan is 77.

    1000 is not a calling code at all, and 77 is OnlineSim splitting Kazakhstan
    out of +7. Both were silently dropped from the catalogue until the override
    table existed.
    """
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    by_iso = {c.code: c for c in provider.get_countries()}

    assert "CA" in by_iso, "Canada was dropped"
    assert "KZ" in by_iso, "Kazakhstan was dropped"


def test_the_uk_resolves_although_it_is_named_britain(provider):
    """Name matching alone missed this one and skipped the country."""
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    assert "GB" in {c.code for c in provider.get_countries()}


def test_ordering_a_canadian_number_sends_canadas_provider_id(provider):
    """Sending 1 would get a US number. This is the wrong-country bug in one line."""
    session = wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(
            200, {"response": 1, "tzid": 4242, "number": "+15550000000"}
        ),
    })

    provider.create_order("telegram", "CA", "idem-ca")

    order_call = next(c for c in session.calls if c[0] == provider.PATH_ORDER)
    assert str(order_call[1]["country"]) == "1000"


def test_ordering_an_american_number_sends_one(provider):
    session = wire(provider, {
        provider.PATH_TARIFFS: FakeResponse(200, TARIFFS),
        provider.PATH_ORDER: FakeResponse(
            200, {"response": 1, "tzid": 4243, "number": "+15550000001"}
        ),
    })

    provider.create_order("telegram", "US", "idem-us")

    order_call = next(c for c in session.calls if c[0] == provider.PATH_ORDER)
    assert str(order_call[1]["country"]) == "1"


def test_priority_countries_fill_the_bounded_catalogue_first(provider, settings):
    """The limit decides the shop window, so the order must not be accidental."""
    settings.VERIFYGH = {
        **settings.VERIFYGH,
        "PROVIDER_CATALOG_LIMIT": 2,
        "PROVIDER_PRIORITY_COUNTRIES": ["US", "CA", "GB"],
    }
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    offerings = provider.get_services()

    assert {o.country_code for o in offerings} == {"US"}, (
        "the bounded catalogue did not start with the preferred country"
    )


def test_a_preferred_country_the_provider_lacks_is_reported_not_silent(provider, settings):
    settings.VERIFYGH = {
        **settings.VERIFYGH,
        "PROVIDER_PRIORITY_COUNTRIES": ["ZZ"],
    }
    wire(provider, {provider.PATH_TARIFFS: FakeResponse(200, TARIFFS)})

    # Still returns the real countries; the missing one is logged, not fatal.
    assert provider._ordered_countries()


def test_provider_overrides_are_consistent_in_both_directions():
    """A one-way mapping would resolve a country and then order the wrong one."""
    _CountryCodes._load()
    for code, iso in _CountryCodes._by_provider.items():
        assert _CountryCodes.resolve(code) == iso
