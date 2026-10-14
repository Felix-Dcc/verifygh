"""Number rentals, end to end against the mock provider.

The money rules are the ones orders follow: the price is the server's, the
wallet is charged once per request key, and whenever the provider gives the
customer nothing the money comes back to the bucket it came from.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.rentals import services
from apps.rentals.models import ExtensionStatus, Rental, RentalExtension, RentalStatus
from apps.rentals.tasks import poll_rental_messages, process_rentals, purge_rental_messages
from apps.verification import mock as verification_mock
from apps.wallet.models import FundType, LedgerDirection, LedgerEntryType, WalletLedgerEntry
from apps.wallet.services import (
    get_or_create_wallet,
    net_spending,
    post_entry,
    verify_wallet_integrity,
)

pytestmark = pytest.mark.django_db

_capture = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture
    _capture = django_capture_on_commit_callbacks
    yield
    _capture = None


@pytest.fixture(autouse=True)
def _quiet_inbox():
    # No automatic first message unless a test sends one.
    verification_mock.force_rental_mode("QUIET")
    yield


#: Mock prices at the test rate (12.00) and the 40% markup, rounded up to GH₵0.50:
#: a single-app number for 30 days costs 4.80 x 12 x 1.4 = 80.64 -> 81.00.
WHATSAPP_30 = Decimal("81.00")
#: 3.00 x 12 x 1.4 = 50.40 -> 50.50
WHATSAPP_7 = Decimal("50.50")
#: 10.00 x 12 x 1.4 = 168.00
ALL_30 = Decimal("168.00")


def rent(client, service="whatsapp", days=30, key=None, expected=None):
    body = {"service": service, "days": days}
    if key:
        body["idempotency_key"] = key
    if expected is not None:
        body["expected_price"] = str(expected)
    with _capture(execute=True):
        return client.post("/api/v1/rentals/", body, format="json")


def fresh(rental: Rental) -> Rental:
    return Rental.objects.select_related("provider", "service", "user").get(pk=rental.pk)


def age(rental: Rental, **delta) -> None:
    Rental.objects.filter(pk=rental.pk).update(created_at=timezone.now() - timedelta(**delta))


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def test_prices_are_the_provider_price_times_the_rate_plus_forty_percent(user, auth, catalog):
    client = auth(user)
    data = client.get("/api/v1/rentals/options/", {"service": "whatsapp"}).data

    by_days = {entry["days"]: entry for entry in data["durations"]}
    assert [entry["days"] for entry in data["durations"]] == [1, 3, 7, 14, 30, 90]
    assert Decimal(by_days[30]["price"]) == WHATSAPP_30
    assert Decimal(by_days[7]["price"]) == WHATSAPP_7
    assert data["service_name"] == "WhatsApp"


def test_an_any_app_number_has_no_one_day_rental(user, auth, catalog):
    client = auth(user)
    data = client.get("/api/v1/rentals/options/", {"service": "all"}).data

    by_days = {entry["days"]: entry for entry in data["durations"]}
    assert data["all_services"] is True
    assert by_days[1]["available"] is False and by_days[1]["price"] is None
    assert Decimal(by_days[30]["price"]) == ALL_30


def test_the_price_always_rounds_up_never_down():
    assert services.customer_price(Decimal("4.80"), Decimal("12.96")) == Decimal("87.50")
    assert services.customer_price(Decimal("10.00"), Decimal("12.00")) == Decimal("168.00")
    assert services.customer_price(Decimal("0.01"), Decimal("12.00")) == Decimal("0.50")


def test_the_services_list_and_lengths_are_offered(user, auth, catalog):
    data = auth(user).get("/api/v1/rentals/services/").data
    slugs = {service["slug"] for service in data["services"]}
    assert {"whatsapp", "telegram"} <= slugs
    assert [entry["days"] for entry in data["durations"]] == [1, 3, 7, 14, 30, 90]


# ---------------------------------------------------------------------------
# Buying
# ---------------------------------------------------------------------------


def test_renting_a_number_charges_the_wallet_and_hands_over_the_number(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    response = rent(client, expected=WHATSAPP_30)
    assert response.status_code == 201, response.data
    # The number is fetched once the charge has committed.
    assert response.data["status"] == RentalStatus.PENDING
    assert Decimal(response.data["price"]) == WHATSAPP_30
    detail = client.get(f"/api/v1/rentals/{response.data['reference']}/").data
    assert detail["status"] == RentalStatus.ACTIVE
    assert detail["phone_number"].startswith("+1")

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30
    rental = Rental.objects.get(reference=response.data["reference"])
    assert rental.ends_at > timezone.now() + timedelta(days=29)
    assert rental.cash_amount == WHATSAPP_30 and rental.promo_amount == 0
    assert Notification.objects.filter(user=user, event="RENTAL_ACTIVE").exists()
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_a_retry_with_the_same_key_rents_and_charges_once(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "300.00")
    client = auth(user)

    first = rent(client, key="rent-key-0001")
    second = rent(client, key="rent-key-0001")

    assert first.data["reference"] == second.data["reference"]
    assert Rental.objects.filter(user=user).count() == 1
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("300.00") - WHATSAPP_30


def test_a_price_that_moved_since_it_was_shown_is_refused_and_nothing_is_charged(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    client = auth(user)

    response = rent(client, expected=Decimal("70.00"))

    assert response.status_code == 409
    assert response.data["error"]["code"] == "PRICE_CHANGED"
    assert Decimal(response.data["error"]["details"]["price"]) == WHATSAPP_30
    assert not Rental.objects.exists()
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_a_purchase_always_uses_the_live_price_not_the_shown_one(
        user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    client.get("/api/v1/rentals/options/", {"service": "whatsapp"})  # caches 4.80
    verification_mock.set_rental_price("whatsapp", 30, "5.00")

    response = rent(client, expected=WHATSAPP_30)

    assert response.status_code == 409
    assert response.data["error"]["code"] == "PRICE_CHANGED"
    # 5.00 x 12 x 1.4 = 84.00
    assert response.data["error"]["details"]["price"] == "84.00"


def test_not_enough_money_rents_nothing(user, auth, catalog, funded_wallet):
    funded_wallet(user, "20.00")
    response = rent(auth(user))
    assert response.status_code == 409
    assert response.data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert not Rental.objects.exists()


def test_promotional_credit_is_spent_first_and_returned_as_promotional_credit(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "100.00")
    post_entry(wallet=wallet, amount=Decimal("10.00"), entry_type=LedgerEntryType.REFERRAL_BONUS,
               direction=LedgerDirection.CREDIT, idempotency_key="promo-test",
               funds=FundType.PROMO)
    verification_mock.force_rental_mode("REFUSE")

    response = rent(auth(user))

    rental = Rental.objects.get(reference=response.data["reference"])
    assert rental.promo_amount == Decimal("10.00")
    assert rental.cash_amount == WHATSAPP_30 - Decimal("10.00")
    assert rental.status == RentalStatus.FAILED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("100.00")
    assert wallet.promo_balance == Decimal("10.00")
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_out_of_stock_is_refused_before_charging(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    verification_mock.force_rental_mode("NO_STOCK")

    response = rent(auth(user))

    assert response.status_code == 503
    assert response.data["error"]["code"] == "NO_AVAILABILITY"
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_a_refused_purchase_is_refunded_in_full(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    verification_mock.force_rental_mode("REFUSE")

    response = rent(auth(user))

    assert response.status_code == 201
    rental = Rental.objects.get(reference=response.data["reference"])
    assert rental.status == RentalStatus.FAILED
    assert rental.refunded_amount == WHATSAPP_30
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert WalletLedgerEntry.objects.filter(
        entry_type=LedgerEntryType.REFUND, related_order_id=rental.id).count() == 1
    assert net_spending(wallet, created_at__gte=timezone.now() - timedelta(days=1)) == 0


def test_a_lost_answer_is_followed_up_with_the_same_key_and_never_buys_twice(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    verification_mock.force_rental_mode("TIMEOUT")

    response = rent(auth(user))
    rental = Rental.objects.get(reference=response.data["reference"])
    # The provider did rent the number, but we never heard: still ours to settle.
    assert rental.status == RentalStatus.PENDING
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30

    age(rental, seconds=60)
    process_rentals()

    rental = fresh(rental)
    assert rental.status == RentalStatus.ACTIVE
    assert rental.provider_rental_id
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30


def test_a_purchase_still_processing_upstream_waits_then_activates(
        user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    verification_mock.force_rental_mode("PENDING")

    response = rent(auth(user))
    rental = Rental.objects.get(reference=response.data["reference"])
    assert rental.status == RentalStatus.PENDING
    assert rental.provider_sale_id

    verification_mock.force_rental_mode("QUIET")
    age(rental, seconds=60)
    process_rentals()
    assert fresh(rental).status == RentalStatus.ACTIVE


def test_a_purchase_never_confirmed_is_refunded_after_the_give_up_time(
        user, auth, catalog, funded_wallet, monkeypatch):
    wallet = funded_wallet(user, "200.00")
    response = rent(auth(user))
    rental = Rental.objects.get(reference=response.data["reference"])
    # Make it look unconfirmed for longer than the give-up window.
    Rental.objects.filter(pk=rental.pk).update(status=RentalStatus.PENDING,
                                               provider_rental_id="", provider_sale_id="")
    age(rental, minutes=45)

    def lost(*args, **kwargs):
        from apps.common.errors import ProviderError

        raise ProviderError("The verification provider did not respond in time.")

    monkeypatch.setattr(verification_mock.MockVerificationProvider, "create_rental", lost)
    process_rentals()

    rental = fresh(rental)
    assert rental.status == RentalStatus.FAILED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_one_customer_may_hold_only_so_many_rentals(user, auth, catalog, funded_wallet, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "RENTAL_MAX_ACTIVE": 2}
    funded_wallet(user, "500.00")
    client = auth(user)
    assert rent(client, key="limit-key-0001").status_code == 201
    assert rent(client, key="limit-key-0002").status_code == 201

    third = rent(client, key="limit-key-0003")
    assert third.status_code == 429
    assert third.data["error"]["code"] == "TOO_MANY_RENTALS"


def test_an_unverified_email_cannot_rent(user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    type(user).objects.filter(pk=user.pk).update(is_email_verified=False)
    response = rent(client)
    assert response.status_code == 403
    assert not Rental.objects.exists()


def test_rentals_can_be_switched_off(user, auth, catalog, funded_wallet, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "RENTALS_ENABLED": False}
    funded_wallet(user, "200.00")
    response = rent(auth(user))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "RENTALS_UNAVAILABLE"


def test_a_customer_sees_only_their_own_rentals(user, other_user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    reference = rent(auth(user)).data["reference"]

    other = auth(other_user, "Correct-Horse-Battery-2")
    assert other.get(f"/api/v1/rentals/{reference}/").status_code == 404
    assert other.get("/api/v1/rentals/").data["results"] == []


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


def test_messages_arrive_in_the_inbox_and_the_nudge_carries_no_code(
        user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    rental = Rental.objects.get(reference=reference)

    verification_mock.send_rental_sms(rental.provider_rental_id,
                                      "Your WhatsApp code is 123-456", code="123456")
    detail = client.get(f"/api/v1/rentals/{reference}/").data

    assert len(detail["messages"]) == 1
    assert detail["messages"][0]["code"] == "123456"
    assert "123-456" in detail["messages"][0]["body"]
    nudge = Notification.objects.get(user=user, event="RENTAL_MESSAGE")
    assert "123" not in nudge.body

    # Read again: nothing is stored twice.
    services.sync_messages(fresh(rental))
    assert rental.messages.count() == 1


def test_the_sweep_reads_inboxes_nobody_is_looking_at(user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    rental = Rental.objects.get(reference=rent(auth(user)).data["reference"])
    verification_mock.send_rental_sms(rental.provider_rental_id, "Hello", code="")

    assert poll_rental_messages()["new"] == 1
    # Read again within the poll interval: nobody is asked twice.
    assert poll_rental_messages()["polled"] == 0


def test_message_text_is_hidden_where_codes_may_not_be_shown(
        user, auth, catalog, funded_wallet, settings):
    funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    rental = Rental.objects.get(reference=reference)
    verification_mock.send_rental_sms(rental.provider_rental_id, "Code 999111", code="999111")
    settings.VERIFYGH = {**settings.VERIFYGH, "DISPLAY_VERIFICATION_CODES": False}

    detail = client.get(f"/api/v1/rentals/{reference}/").data
    assert detail["messages"] == [] and detail["messages_hidden"] is True


def test_old_message_text_is_purged_after_the_rental_ends(user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    rental = Rental.objects.get(reference=rent(auth(user)).data["reference"])
    verification_mock.send_rental_sms(rental.provider_rental_id, "Code 555", code="555")
    services.sync_messages(fresh(rental))
    Rental.objects.filter(pk=rental.pk).update(
        status=RentalStatus.EXPIRED, ended_at=timezone.now() - timedelta(days=40))

    assert purge_rental_messages() == 1
    message = rental.messages.get()
    assert message.body == "" and message.code == ""


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


def test_a_rental_cancelled_while_the_provider_allows_is_refunded(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    assert client.get(f"/api/v1/rentals/{reference}/").data["can_cancel"] is True

    response = client.post(f"/api/v1/rentals/{reference}/cancel/", {}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["status"] == RentalStatus.REFUNDED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    # A second click refunds nothing more.
    again = client.post(f"/api/v1/rentals/{reference}/cancel/", {}, format="json")
    assert again.status_code == 409
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_a_rental_the_provider_will_not_refund_cannot_be_cancelled(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    rental = Rental.objects.get(reference=reference)
    verification_mock.block_rental_refund(rental.provider_rental_id)

    response = client.post(f"/api/v1/rentals/{reference}/cancel/", {}, format="json")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "RENTAL_NOT_REFUNDABLE"
    assert fresh(rental).status == RentalStatus.ACTIVE
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30


def test_a_rental_that_received_a_message_cannot_be_cancelled(
        user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    rental = Rental.objects.get(reference=reference)
    verification_mock.send_rental_sms(rental.provider_rental_id, "Code 1", code="1")

    response = client.post(f"/api/v1/rentals/{reference}/cancel/", {}, format="json")
    assert response.status_code == 409
    assert fresh(rental).status == RentalStatus.ACTIVE


# ---------------------------------------------------------------------------
# Extending
# ---------------------------------------------------------------------------


def test_extending_charges_for_the_days_and_moves_the_end(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "300.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    before = Rental.objects.get(reference=reference).ends_at

    quoted = client.get(f"/api/v1/rentals/{reference}/extension-quote/", {"days": 7}).data
    assert Decimal(quoted["price"]) == WHATSAPP_7
    response = client.post(f"/api/v1/rentals/{reference}/extend/",
                           {"days": 7, "expected_price": quoted["price"]}, format="json")

    assert response.status_code == 200, response.data
    rental = Rental.objects.get(reference=reference)
    assert rental.ends_at >= before + timedelta(days=7) - timedelta(seconds=5)
    extension = rental.extensions.get()
    assert extension.status == ExtensionStatus.COMPLETED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("300.00") - WHATSAPP_30 - WHATSAPP_7
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_an_extension_the_provider_refuses_is_refunded(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "300.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    verification_mock.force_rental_mode("REFUSE")

    response = client.post(f"/api/v1/rentals/{reference}/extend/", {"days": 7}, format="json")

    assert response.status_code == 200
    extension = RentalExtension.objects.get()
    assert extension.status == ExtensionStatus.FAILED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("300.00") - WHATSAPP_30
    assert verify_wallet_integrity(wallet)["ok"] is True


def test_an_extension_whose_answer_was_lost_is_settled_from_the_end_date(
        user, auth, catalog, funded_wallet, monkeypatch):
    wallet = funded_wallet(user, "300.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    real_extend = verification_mock.MockVerificationProvider.extend_rental

    def extended_but_lost(self, provider_rental_id, days):
        from apps.common.errors import ProviderError

        real_extend(self, provider_rental_id, days)
        raise ProviderError("The verification provider did not respond in time.")

    monkeypatch.setattr(verification_mock.MockVerificationProvider, "extend_rental",
                        extended_but_lost)
    client.post(f"/api/v1/rentals/{reference}/extend/", {"days": 7}, format="json")

    extension = RentalExtension.objects.get()
    assert extension.status == ExtensionStatus.COMPLETED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("300.00") - WHATSAPP_30 - WHATSAPP_7


# ---------------------------------------------------------------------------
# The end of the period
# ---------------------------------------------------------------------------


def test_a_rental_past_its_end_is_closed_without_a_refund(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    rental = Rental.objects.get(reference=rent(auth(user)).data["reference"])
    verification_mock.end_rental_upstream(rental.provider_rental_id, "EXPIRED")
    Rental.objects.filter(pk=rental.pk).update(ends_at=timezone.now() - timedelta(minutes=1))

    process_rentals()

    rental = fresh(rental)
    assert rental.status == RentalStatus.EXPIRED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30
    # Delivered, so it counts as spent.
    today = timezone.localdate()
    assert net_spending(wallet, successful_only=True, created_at__date=today) == WHATSAPP_30


def test_a_rental_the_provider_refunds_on_its_own_is_refunded_to_the_customer(
        user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    rental = Rental.objects.get(reference=rent(auth(user)).data["reference"])
    verification_mock.end_rental_upstream(rental.provider_rental_id, "REFUNDED")

    services.refresh_rental(fresh(rental))

    assert fresh(rental).status == RentalStatus.REFUNDED
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00")


def test_a_reminder_is_sent_once_before_the_end(user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    rental = Rental.objects.get(reference=rent(auth(user)).data["reference"])
    Rental.objects.filter(pk=rental.pk).update(ends_at=timezone.now() + timedelta(hours=10))

    process_rentals()
    process_rentals()

    assert Notification.objects.filter(user=user, event="RENTAL_ENDING",
                                       channel="IN_APP").count() == 1


def test_the_admin_list_shows_rentals_to_staff_only(user, admin_user, auth, catalog,
                                                    funded_wallet, api):
    funded_wallet(user, "200.00")
    reference = rent(auth(user)).data["reference"]
    assert api.get("/api/v1/admin/rentals/").status_code == 403

    staff = auth(admin_user, "Correct-Horse-Battery-3")
    rows = staff.get("/api/v1/admin/rentals/").data["results"]
    assert [row["reference"] for row in rows] == [reference]
    summary = staff.get("/api/v1/admin/rentals/summary/").data
    assert summary["active"] == 1 and Decimal(summary["takings"]) == WHATSAPP_30


def test_wallet_balance_is_untouched_by_reads(user, auth, catalog, funded_wallet):
    wallet = funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    for _ in range(3):
        client.get(f"/api/v1/rentals/{reference}/")
        client.get("/api/v1/rentals/")
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("200.00") - WHATSAPP_30
    assert get_or_create_wallet(user).pk == wallet.pk


def test_the_cancel_button_goes_once_a_message_closes_the_refund_window(
        user, auth, catalog, funded_wallet):
    funded_wallet(user, "200.00")
    client = auth(user)
    reference = rent(client).data["reference"]
    rental = Rental.objects.get(reference=reference)
    assert client.get(f"/api/v1/rentals/{reference}/").data["can_cancel"] is True

    from django.core.cache import cache

    cache.delete(f"rental-live-sync:{rental.pk}")
    verification_mock.send_rental_sms(rental.provider_rental_id, "Code 42", code="42")
    detail = client.get(f"/api/v1/rentals/{reference}/").data

    assert len(detail["messages"]) == 1
    assert detail["can_cancel"] is False
