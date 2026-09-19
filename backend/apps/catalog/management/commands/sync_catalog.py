from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.catalog.services import sync_catalog


class Command(BaseCommand):
    help = "Sync services, countries, costs and availability from the verification provider."

    def add_arguments(self, parser):
        parser.add_argument("--provider", help="Adapter key (defaults to VERIFICATION_PROVIDER).")

    def handle(self, *args, **options):
        summary = sync_catalog(options.get("provider"))
        self.stdout.write(json.dumps(summary, indent=2, default=str))
        if summary["errors"]:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Catalog synced."))
