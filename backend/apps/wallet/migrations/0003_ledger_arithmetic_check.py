"""Every ledger row's arithmetic is checked by the database itself.

balance_after must equal balance_before plus (credit) or minus (debit) amount.
PostgreSQL only: its NUMERIC is exact. SQLite stores decimals with REAL
affinity, where 0.10 + 0.20 is not 0.30, so the same check would reject
correct rows there. Development on SQLite keeps the application-level check in
verify_wallet_integrity; production gets both.
"""

from django.db import migrations

CONSTRAINT = "ledger_arithmetic_consistent"

ADD = f"""
ALTER TABLE wallet_ledger_entry ADD CONSTRAINT {CONSTRAINT} CHECK (
    (direction = 'CREDIT' AND balance_after = balance_before + amount)
    OR (direction = 'DEBIT' AND balance_after = balance_before - amount)
)
"""

DROP = f"ALTER TABLE wallet_ledger_entry DROP CONSTRAINT IF EXISTS {CONSTRAINT}"


def add(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(ADD)


def drop(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [("wallet", "0002_integrity_constraints")]

    operations = [migrations.RunPython(add, drop)]
