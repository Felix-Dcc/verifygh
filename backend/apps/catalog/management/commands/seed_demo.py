"""Bring an empty database up to a working, demonstrable state.

    python manage.py seed_demo

Creates the minimum a marketplace needs to function - an exchange rate, a
global pricing rule, the provider catalog - plus optional demo accounts.

Safe to re-run: everything is get_or_create or an append.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.catalog.services import sync_catalog
from apps.pricing.models import MarkupType, PricingRule, Rounding
from apps.pricing.rates import latest_rate_row, record_rate

DEMO_PASSWORD = "VerifyGH-Demo-2026"


class Command(BaseCommand):
    help = "Seed exchange rate, pricing rules, provider catalog and demo accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rate", default="12.40",
            help="USD to GHS rate to seed if none exists (dev only - production uses a feed).",
        )
        parser.add_argument("--no-accounts", action="store_true",
                            help="Skip creating demo accounts.")
        parser.add_argument("--admin-email", default="admin@verifygh.local")
        parser.add_argument("--user-email", default="kwame@example.com")

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding VerifyGH"))

        rate = self._seed_rate(options["rate"])
        rule = self._seed_pricing_rule()
        summary = self._seed_catalog()

        if not options["no_accounts"]:
            self._seed_accounts(options["admin_email"], options["user_email"])

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(f"  exchange rate : 1 USD = {rate.rate} GHS ({rate.source})")
        self.stdout.write(f"  pricing rule  : {rule.name}")
        self.stdout.write(
            f"  catalog       : {summary['offerings']} offerings from "
            f"{summary['provider']} ({summary['unavailable']} out of stock)"
        )
        if summary["errors"]:
            self.stdout.write(self.style.WARNING(f"  sync errors   : {summary['errors']}"))

    def _seed_rate(self, value: str):
        existing = latest_rate_row("USD", "GHS")
        if existing is not None:
            self.stdout.write(f"  exchange rate already set ({existing.rate}), leaving it alone")
            return existing
        self.stdout.write(self.style.WARNING(
            "  no exchange rate found - seeding a development placeholder. "
            "Set EXCHANGE_RATE_PROVIDER and a real feed before production."
        ))
        return record_rate(
            Decimal(value), source="manual", note="Seeded by seed_demo (development only)."
        )

    def _seed_pricing_rule(self) -> PricingRule:
        rule, created = PricingRule.objects.get_or_create(
            service=None,
            country=None,
            defaults={
                "name": "Global default",
                "markup_type": MarkupType.PERCENTAGE,
                "markup_percent": Decimal("20.00"),
                "payment_fee_percent": Decimal("2.00"),
                "risk_buffer_percent": Decimal("3.00"),
                "rounding": Rounding.NEAREST_0_50,
                "min_price": Decimal("3.00"),
                "max_price": Decimal("500.00"),
                "priority": 1000,
            },
        )
        self.stdout.write(
            f"  pricing rule {'created' if created else 'already present'}: {rule.name}"
        )
        return rule

    def _seed_catalog(self) -> dict:
        provider_key = settings.VERIFYGH["VERIFICATION_PROVIDER"]
        self.stdout.write(f"  syncing catalog from provider '{provider_key}'...")
        return sync_catalog()

    def _seed_accounts(self, admin_email: str, user_email: str) -> None:
        if not settings.DEBUG:
            self.stdout.write(self.style.WARNING(
                "  DEBUG is off - skipping demo accounts. Create real accounts with "
                "createsuperuser instead."
            ))
            return

        admin, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                "full_name": "VerifyGH Admin",
                "role": Role.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_email_verified": True,
                "accepted_terms_version": settings.VERIFYGH["CURRENT_TERMS_VERSION"],
            },
        )
        if created:
            admin.set_password(DEMO_PASSWORD)
            admin.save(update_fields=["password"])

        customer, created_user = User.objects.get_or_create(
            email=user_email,
            defaults={
                "full_name": "Kwame Mensah",
                "phone": "+233241234567",
                "is_email_verified": True,
                "accepted_terms_version": settings.VERIFYGH["CURRENT_TERMS_VERSION"],
            },
        )
        if created_user:
            customer.set_password(DEMO_PASSWORD)
            customer.save(update_fields=["password"])

        self.stdout.write("  demo accounts:")
        self.stdout.write(f"    admin : {admin_email} / {DEMO_PASSWORD}")
        self.stdout.write(f"    user  : {user_email} / {DEMO_PASSWORD}")
        self.stdout.write(self.style.WARNING(
            "    These are development credentials. Never seed them in production."
        ))
