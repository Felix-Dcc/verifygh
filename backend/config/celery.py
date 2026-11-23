"""Celery application and beat schedule.

Periodic work is deliberately conservative: we poll our *own* database for due
work and only touch the upstream provider for orders that are actually waiting.
Provider calls are additionally rate-limited in apps/verification/registry.py.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("verifygh")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "poll-active-orders": {
        "task": "apps.orders.tasks.poll_active_orders",
        "schedule": 10.0,
    },
    "expire-stale-orders": {
        "task": "apps.orders.tasks.expire_stale_orders",
        "schedule": 60.0,
    },
    "expire-stale-payments": {
        "task": "apps.payments.tasks.expire_stale_payments",
        "schedule": 60.0,
    },
    "refresh-exchange-rate": {
        "task": "apps.pricing.tasks.refresh_exchange_rate",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # Out-of-stock offerings only: returning stock shows within two minutes.
    "recheck-stock": {
        "task": "apps.catalog.tasks.recheck_stock",
        "schedule": 120.0,
    },
    "sync-provider-catalog": {
        "task": "apps.catalog.tasks.sync_provider_catalog",
        "schedule": crontab(minute=15, hour="*/3"),
    },
    # The second supplier's prices (public, no key needed). Nothing is sold
    # through it until staff record its resale permission in Admin > Providers.
    "sync-smspool-catalog": {
        "task": "apps.catalog.tasks.sync_provider_catalog",
        "schedule": crontab(minute=45, hour="*/3"),
        "args": ("smspool",),
    },
    "sync-numberotp-catalog": {
        "task": "apps.catalog.tasks.sync_provider_catalog",
        "schedule": crontab(minute=55, hour="*/3"),
        "args": ("numberotp",),
    },
    # Our prepaid balance at each provider: read it, grade it, alert staff.
    # One getBalance call per provider every two minutes.
    "sync-provider-balances": {
        "task": "apps.funding.tasks.sync_provider_balances",
        "schedule": 120.0,
    },
    "reconcile-wallets": {
        "task": "apps.wallet.tasks.reconcile_wallets",
        "schedule": crontab(minute=30, hour=2),
    },
    # Without this the token blacklist grows with every sign-in, forever.
    "flush-expired-tokens": {
        "task": "apps.accounts.tasks.flush_expired_tokens",
        "schedule": crontab(minute=0, hour=3),
    },
    # Makes the Privacy Policy's retention window true rather than aspirational.
    "prune-login-attempts": {
        "task": "apps.accounts.tasks.prune_login_attempts",
        "schedule": crontab(minute=20, hour=3, day_of_week=0),
    },
    # Finishes callbacks that were verified and recorded but failed to apply.
    "retry-failed-webhooks": {
        "task": "apps.payments.tasks.retry_failed_webhooks",
        "schedule": 300.0,
    },
    # A stored verification code is a standing risk to the account it unlocked.
    "purge-verification-data": {
        "task": "apps.orders.tasks.purge_verification_data",
        "schedule": crontab(minute=40, hour=3),
    },
    # Settles referrals that became eligible while the programme was paused,
    # or whose referrer was at their monthly cap. Idempotent by construction.
    "process-pending-referrals": {
        "task": "apps.referrals.tasks.process_pending_referrals",
        "schedule": crontab(minute="*/30"),
    },
    # Refunds customers once the provider refunds a verification they reported.
    "check-provider-refunds": {
        "task": "apps.numbers.tasks.check_provider_refunds",
        "schedule": crontab(minute="*/10"),
    },
    # Number rentals: confirm purchases, close ended ones, send reminders.
    "process-rentals": {
        "task": "apps.rentals.tasks.process_rentals",
        "schedule": 30.0,
    },
    # Each active rental's inbox, at most every RENTAL_SMS_POLL_SECONDS.
    "poll-rental-messages": {
        "task": "apps.rentals.tasks.poll_rental_messages",
        "schedule": 60.0,
    },
    "purge-rental-messages": {
        "task": "apps.rentals.tasks.purge_rental_messages",
        "schedule": crontab(minute=50, hour=3),
    },
    # Rentals refunded for want of an answer: did the provider sell them after all?
    "reconcile-given-up-rentals": {
        "task": "apps.rentals.tasks.reconcile_given_up_rentals",
        "schedule": crontab(minute="5-59/15"),
    },
    # Catches deposits whose provider callback never arrived.
    "reconcile-recent-payments": {
        "task": "apps.payments.tasks.reconcile_recent_payments",
        "schedule": crontab(minute="*/15"),
    },
}
