"""Re-derive every wallet balance from the ledger.

    python manage.py reconcile_wallets

Exits non-zero when any wallet has drifted, so it can be wired to an alert.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.wallet.models import Wallet
from apps.wallet.services import verify_wallet_integrity


class Command(BaseCommand):
    help = "Verify that every wallet balance matches its ledger."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
        parser.add_argument("--user", help="Check a single user by email.")

    def handle(self, *args, **options):
        queryset = Wallet.objects.select_related("user")
        if options.get("user"):
            queryset = queryset.filter(user__email__iexact=options["user"])

        reports = [verify_wallet_integrity(wallet) for wallet in queryset]
        broken = [report for report in reports if not report["ok"]]

        if options.get("json"):
            self.stdout.write(json.dumps({"checked": len(reports), "broken": broken}, indent=2))
        else:
            self.stdout.write(f"Checked {len(reports)} wallet(s).")
            for report in broken:
                self.stderr.write(
                    self.style.ERROR(
                        f"  DRIFT wallet={report['wallet_id']} "
                        f"stored={report['stored_balance']} derived={report['derived_balance']} "
                        f"chain_breaks={len(report['chain_breaks'])}"
                    )
                )
            if not broken:
                self.stdout.write(self.style.SUCCESS("All wallets reconcile with their ledgers."))

        if broken:
            raise SystemExit(1)
