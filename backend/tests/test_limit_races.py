"""A-12: per-user limits hold exactly when requests arrive together.

The limits are counts over other rows (orders in progress, the day's spending,
open rentals, unfinished top-ups), which no database constraint can enforce.
They were checked before the purchase's transaction, so two requests sent at
once both passed and both went through. Each is now re-checked under the
wallet's row lock. Real threads behind a barrier, as in
test_concurrency_flows.py; on PostgreSQL (CI) the row lock serialises them.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import connections

from apps.common.errors import APIError
from apps.orders.models import Order
from apps.payments.models import Payment, PaymentStatus
from apps.rentals.models import Rental
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(target, count: int = 2) -> list:
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def _worker(index: int):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except APIError as exc:
            results[index] = ("refused", exc.code)
        except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
            results[index] = ("error", repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def _limits(settings, **values):
    settings.VERIFYGH = {**settings.VERIFYGH, **values}


def _fresh_user(user_pk):
    from apps.accounts.models import User

    return User.objects.get(pk=user_pk)


def _buy(user_pk, key):
    from apps.orders.services import create_order

    return create_order(user=_fresh_user(user_pk), service_slug="instagram", country_code="US",
                        idempotency_key=key).pk


def _price():
    from apps.orders.services import quote

    return Decimal(quote("instagram", "US")["price"])


def _codes(results, outcome="refused"):
    return [code for kind, code in results if kind == outcome]


def test_two_orders_sent_together_respect_the_active_order_limit(
        user, catalog, funded_wallet, settings):
    _limits(settings, MAX_ACTIVE_ORDERS=1)
    funded_wallet(user, "200.00")

    results = run_concurrently(lambda index: _buy(user.pk, f"active-{index}"))

    assert sorted(kind for kind, _ in results) == ["ok", "refused"], results
    assert _codes(results) == ["TOO_MANY_ACTIVE_ORDERS"]
    assert Order.objects.filter(user=user).count() == 1


def test_two_orders_sent_together_respect_the_daily_spending_limit(
        user, catalog, funded_wallet, settings):
    price = _price()
    _limits(settings, MAX_DAILY_SPEND=str(price + price / 2))
    funded_wallet(user, "200.00")

    results = run_concurrently(lambda index: _buy(user.pk, f"spend-{index}"))

    assert sorted(kind for kind, _ in results) == ["ok", "refused"], results
    assert _codes(results) == ["DAILY_SPEND_LIMIT"]
    assert Order.objects.filter(user=user).count() == 1


def test_two_rentals_sent_together_respect_the_open_rental_limit(
        user, catalog, funded_wallet, settings):
    from apps.rentals.services import create_rental

    _limits(settings, RENTAL_MAX_ACTIVE=1)
    verification_mock.force_rental_mode("QUIET")
    funded_wallet(user, "400.00")

    def rent(index):
        return create_rental(user=_fresh_user(user.pk), service_key="whatsapp", days=30,
                             idempotency_key=f"rental-{index}").pk

    results = run_concurrently(rent)

    assert sorted(kind for kind, _ in results) == ["ok", "refused"], results
    assert _codes(results) == ["TOO_MANY_RENTALS"]
    assert Rental.objects.filter(user=user).count() == 1


def test_deposits_started_together_respect_the_pending_limit(user, catalog, settings):
    from apps.payments.services import MAX_PENDING_DEPOSITS, initiate_deposit

    for index in range(MAX_PENDING_DEPOSITS - 1):
        Payment.objects.create(user=user, reference=f"VGH-PEND-{index}", provider="mock",
                               amount=Decimal("10.00"), phone="+233241234567",
                               network="MTN", status=PaymentStatus.PENDING)

    def deposit(index):
        return initiate_deposit(user=_fresh_user(user.pk), amount=Decimal(f"{11 + index}.00"),
                                phone="+233241234567", network="MTN").pk

    results = run_concurrently(deposit)

    assert sorted(kind for kind, _ in results) == ["ok", "refused"], results
    assert _codes(results) == ["TOO_MANY_PENDING_DEPOSITS"]
    assert Payment.objects.filter(user=user).count() == MAX_PENDING_DEPOSITS


def test_manual_top_ups_started_together_respect_the_open_request_limit(user, settings):
    from apps.common.models import MaintenanceState
    from apps.payments import manual

    _limits(settings, MANUAL_DEPOSIT_MAX_OPEN=1, MANUAL_DEPOSIT_NUMBER="0261234567")
    MaintenanceState.objects.update_or_create(pk=1, defaults={"manual_deposits": True})

    results = run_concurrently(
        lambda index: manual.start(user=_fresh_user(user.pk), amount=Decimal("20.00")).pk)

    assert sorted(kind for kind, _ in results) == ["ok", "refused"], results
    assert _codes(results) == ["TOO_MANY_OPEN_TOPUPS"]
    assert Payment.objects.filter(user=user, provider="manual").count() == 1
