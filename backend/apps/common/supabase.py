"""Keep Supabase's auto-generated Data API away from VerifyGH's tables.

Supabase publishes every table in the `public` schema over its REST/GraphQL
Data API, and its default privileges grant the `anon` and `authenticated`
roles access to new tables there. Django creates all of VerifyGH's tables in
`public` - users, wallets, the ledger, payments. VerifyGH never uses that API
(the Django backend is the only client of the database), so anyone holding the
project's anon key could otherwise try to read or write them directly,
bypassing every check in this codebase.

After each `migrate` this module, on a database that has Supabase's roles:
  * revokes all table and sequence privileges in `public` from anon and
    authenticated, now and by default for future objects;
  * enables row-level security on every table in `public`, with no policies,
    so those roles see nothing even if a grant slips back in.

The application connects as the tables' owner, which RLS does not apply to
(it is enabled, not FORCEd), so Django is unaffected. On any other database -
local SQLite, CI PostgreSQL, a plain managed Postgres - this does nothing.

Also turn the Data API off in the Supabase dashboard; this is the second lock.
"""

from __future__ import annotations

import logging

from django.db import connections

logger = logging.getLogger("verifygh.db")

API_ROLES = ("anon", "authenticated")


def _supabase_roles_present(cursor) -> bool:
    cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)", [list(API_ROLES)])
    return cursor.fetchone()[0] == len(API_ROLES)


def lock_down_data_api(using: str = "default") -> int:
    """Apply the lockdown. Returns the number of tables secured (0 if not Supabase)."""
    connection = connections[using]
    if connection.vendor != "postgresql":
        return 0
    with connection.cursor() as cursor:
        if not _supabase_roles_present(cursor):
            return 0
        roles = ", ".join(API_ROLES)
        cursor.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {roles}")
        cursor.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {roles}")
        cursor.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {roles}")
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {roles}"
        )
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {roles}"
        )
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM {roles}"
        )
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity"
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    logger.info("supabase_data_api_locked", extra={"rls_enabled_on": len(tables)})
    return len(tables)


def on_post_migrate(sender, using="default", **kwargs):
    # post_migrate fires once per app - but only for apps with a models module
    # (Django skips the rest). Act on the last of those, so the work runs once,
    # after every table exists. Keying on the last app overall would never fire.
    from django.apps import apps

    receiving = [config for config in apps.get_app_configs() if config.models_module is not None]
    if sender.name != receiving[-1].name:
        return
    lock_down_data_api(using)
