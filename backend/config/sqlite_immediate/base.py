"""SQLite backend that opens every transaction with BEGIN IMMEDIATE.

Test and local-development use only. SQLite's default deferred transactions
take the write lock lazily, so two threads that have both read inside a
transaction deadlock when they try to write, and one fails instantly with
"database is locked" - the busy timeout cannot help. BEGIN IMMEDIATE takes the
write lock up front, so concurrent transactions queue instead of failing, which
is what PostgreSQL's row locks do in production.

Django 5.1 exposes this as OPTIONS["transaction_mode"]; this shim does the same
on 5.0 and can be deleted after an upgrade.
"""

from django.db.backends.sqlite3 import base


class DatabaseWrapper(base.DatabaseWrapper):
    def _start_transaction_under_autocommit(self):
        self.cursor().execute("BEGIN IMMEDIATE")
