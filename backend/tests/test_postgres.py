"""Guarantees that only exist on PostgreSQL, the production database.

SQLite has no row locks, so locally these are skipped and the concurrency
tests exercise the compare-and-set fallback instead. CI runs them against
PostgreSQL 16 with REQUIRE_POSTGRES=1, so a skipped run there is impossible.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

import pytest
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext

from apps.payments.models import Payment
from apps.wallet.models import LedgerDirection, LedgerEntryType, Wallet
from apps.wallet.services import get_or_create_wallet, post_entry

pytestmark = [
    pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL only"),
]


@pytest.mark.django_db
def test_isolation_level_is_read_committed():
    """The ledger's correctness argument assumes READ COMMITTED + row locks:
    a waiter re-reads the locked row's committed version after the holder
    commits. Under REPEATABLE READ it would instead get a serialization error.
    """
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        assert cursor.fetchone()[0] == "read committed"


@pytest.mark.django_db
def test_posting_to_a_wallet_takes_a_row_lock(user):
    wallet = get_or_create_wallet(user)
    with CaptureQueriesContext(connection) as queries:
        post_entry(wallet=wallet, amount=Decimal("5.00"), entry_type=LedgerEntryType.DEPOSIT,
                   direction=LedgerDirection.CREDIT, idempotency_key="lock-check")

    locking = [q["sql"] for q in queries.captured_queries
               if "FOR UPDATE" in q["sql"] and Wallet._meta.db_table in q["sql"]]
    assert locking, "post_entry did not SELECT ... FOR UPDATE the wallet row"


@pytest.mark.django_db
def test_crediting_a_payment_takes_a_row_lock(user):
    from apps.payments.services import _lock_payment

    payment = Payment.objects.create(user=user, reference="VGH-PAY-PGLOCK01", provider="mock",
                                     amount=Decimal("10.00"), phone="+233241234567",
                                     network="MTN")
    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        _lock_payment(payment.pk)

    assert any("FOR UPDATE" in q["sql"] and Payment._meta.db_table in q["sql"]
               for q in queries.captured_queries)


@pytest.mark.django_db(transaction=True)
def test_a_second_writer_waits_for_the_wallet_lock(user, funded_wallet):
    """Observe the lock directly: while one transaction holds the wallet row, a
    debit on another connection blocks, then sees the committed balance."""
    wallet = funded_wallet(user, "20.00")
    holding = threading.Event()
    release = threading.Event()
    finished: dict = {}

    def holder():
        try:
            with transaction.atomic():
                locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
                Wallet.objects.filter(pk=locked.pk).update(balance=Decimal("5.00"))
                holding.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    def spender():
        try:
            holding.wait(timeout=10)
            try:
                post_entry(wallet=Wallet.objects.get(pk=wallet.pk), amount=Decimal("15.00"),
                           entry_type=LedgerEntryType.PURCHASE,
                           direction=LedgerDirection.DEBIT, idempotency_key="blocked")
                finished["result"] = "debited"
            except Exception as exc:  # noqa: BLE001
                finished["result"] = type(exc).__name__
            finished["at"] = time.monotonic()
        finally:
            connections.close_all()

    threads = [threading.Thread(target=holder), threading.Thread(target=spender)]
    for thread in threads:
        thread.start()
    holding.wait(timeout=10)
    time.sleep(0.5)
    assert "result" not in finished, "the debit did not wait for the row lock"
    released_at = time.monotonic()
    release.set()
    for thread in threads:
        thread.join(timeout=30)

    assert finished["at"] >= released_at
    # It read the holder's committed 5.00, not the stale 20.00 it started with.
    assert finished["result"] == "InsufficientFunds"


@pytest.mark.django_db
def test_the_database_rejects_a_ledger_row_whose_arithmetic_is_wrong(user):
    """Even a writer that bypasses post_entry cannot record 10 + 5 = 50."""
    from django.db import IntegrityError

    from apps.wallet.models import WalletLedgerEntry

    wallet = get_or_create_wallet(user)
    with pytest.raises(IntegrityError, match="ledger_arithmetic_consistent"), \
            transaction.atomic():
        WalletLedgerEntry.objects.create(
            wallet=wallet, reference="VGH-LED-BADMATH1", sequence=1, idempotency_key="bad",
            entry_type=LedgerEntryType.DEPOSIT, direction=LedgerDirection.CREDIT,
            amount=Decimal("5.00"), balance_before=Decimal("10.00"),
            balance_after=Decimal("50.00"), currency="GHS",
        )


@pytest.mark.django_db
def test_supabase_data_api_roles_are_locked_out():
    """Recreate Supabase's API roles and its default grant, then migrate-hook.
    CREATE ROLE is transactional, so the test's rollback removes them again."""
    from apps.common.supabase import lock_down_data_api

    with connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        existing = {row[0] for row in cursor.fetchall()}
        for role in {"anon", "authenticated"} - existing:
            cursor.execute(f"CREATE ROLE {role} NOLOGIN")
        cursor.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated")
        cursor.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")

        assert lock_down_data_api() > 0

        for table in ("wallet_wallet", "wallet_ledger_entry", "payments_payment",
                      "accounts_user"):
            for role in ("anon", "authenticated"):
                cursor.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", [role, table])
                assert cursor.fetchone()[0] is False, (role, table)
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = %s", [table])
            assert cursor.fetchone()[0] is True, table

    # The application, as table owner, still reads and writes normally.
    from apps.accounts.models import User

    assert User.objects.count() >= 0
