from __future__ import annotations

import logging

from celery import shared_task

from apps.wallet.models import Wallet
from apps.wallet.services import verify_wallet_integrity

logger = logging.getLogger("verifygh.wallet")


@shared_task(name="apps.wallet.tasks.reconcile_wallets")
def reconcile_wallets(limit: int = 5000) -> dict:
    """Re-derive every balance from the ledger and alert on drift.

    Deliberately read-only. If a balance has drifted, that is a bug worth a
    human looking at the ledger - silently "fixing" the number would destroy
    the evidence.
    """
    checked = 0
    broken = []

    for wallet in Wallet.objects.all().iterator(chunk_size=200):
        report = verify_wallet_integrity(wallet)
        checked += 1
        if not report["ok"]:
            broken.append(report)
            logger.error("wallet_integrity_drift", extra={"report": report})
        if checked >= limit:
            break

    if broken:
        logger.error(
            "wallet_reconciliation_failed",
            extra={"checked": checked, "broken_count": len(broken)},
        )
    else:
        logger.info("wallet_reconciliation_ok", extra={"checked": checked})

    return {"checked": checked, "broken": len(broken), "reports": broken[:20]}
