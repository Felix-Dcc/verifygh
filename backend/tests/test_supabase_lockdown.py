"""The Supabase lockdown is inert everywhere except Supabase."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_it_does_nothing_off_supabase():
    from apps.common.supabase import lock_down_data_api

    assert lock_down_data_api() == 0


def test_it_is_wired_to_run_after_migrate():
    from django.db.models.signals import post_migrate

    from apps.common.supabase import on_post_migrate

    assert any(getattr(receiver[1](), "__name__", "") == on_post_migrate.__name__
               or receiver[1]() is on_post_migrate for receiver in post_migrate.receivers)


def test_it_fires_on_an_app_that_actually_receives_post_migrate(monkeypatch):
    from django.apps import apps

    from apps.common import supabase

    calls = []
    monkeypatch.setattr(supabase, "lock_down_data_api", lambda using: calls.append(using))
    receiving = [c for c in apps.get_app_configs() if c.models_module is not None]
    for config in receiving:
        supabase.on_post_migrate(sender=config, using="default")
    assert calls == ["default"]
