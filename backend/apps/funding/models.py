"""Our prepaid accounts with verification providers.

This is VerifyGH's own money, not customers'. Customer wallets are a liability
recorded in the wallet ledger; the balance we hold at a provider is a supplier
prepayment made from operating funds. The two are never mixed: nothing here
touches a wallet, and nothing in the wallet ever pays a provider.

See docs/PROVIDER-FUNDING.md for why the provider balance exists at all
(OnlineSim is prepaid only, with no funding API) and how it is run.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AccountMode(models.TextChoices):
    #: Money must be at the provider before a number can be bought. OnlineSim's
    #: only published model (Terms 4.1).
    PREPAID = "PREPAID", "Prepaid"
    #: A credit limit agreed in writing with the provider. Only for use once a
    #: provider has actually granted one; none has.
    CREDIT = "CREDIT", "Credit agreement"


class BalanceStatus(models.TextChoices):
    HEALTHY = "HEALTHY", "Healthy"
    LOW = "LOW", "Low"
    CRITICAL = "CRITICAL", "Critical"
    UNKNOWN = "UNKNOWN", "Unknown"


class ProviderAccount(BaseModel):
    """What we hold at one provider, and the levels we want to keep it at.

    Amounts are in the provider's currency (USD for OnlineSim), because that is
    what the provider reports and what numbers cost there.
    """

    provider = models.OneToOneField(
        "catalog.Provider", on_delete=models.CASCADE, related_name="funding_account"
    )
    mode = models.CharField(max_length=10, choices=AccountMode.choices,
                            default=AccountMode.PREPAID)
    currency = models.CharField(max_length=3, default="USD")

    # Last reading from the provider. Null until the first successful read.
    #: Spendable balance at the provider. Named apart from wallet `balance` on
    #: purpose: this is our money, and only the ledger service writes wallets.
    available = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    frozen = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    #: The balance before its last change, and when it changed. A top-up is
    #: usually recorded *after* the money has landed - by then `available`
    #: already includes it - and this is how that is recognised.
    previous_available = models.DecimalField(max_digits=14, decimal_places=4,
                                             null=True, blank=True)
    available_changed_at = models.DateTimeField(null=True, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=4,
                                       default=Decimal("0.0000"))

    # Reserve thresholds, set by staff.
    critical_balance = models.DecimalField(max_digits=14, decimal_places=4,
                                           default=Decimal("2.0000"))
    minimum_balance = models.DecimalField(max_digits=14, decimal_places=4,
                                          default=Decimal("5.0000"))
    target_balance = models.DecimalField(max_digits=14, decimal_places=4,
                                         default=Decimal("20.0000"))

    status = models.CharField(max_length=10, choices=BalanceStatus.choices,
                              default=BalanceStatus.UNKNOWN)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_attempt_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.CharField(max_length=255, blank=True, default="")
    consecutive_sync_failures = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "funding_provider_account"

    def __str__(self) -> str:
        return f"{self.provider} account"

    @property
    def spendable(self) -> Decimal | None:
        """What a purchase can draw on right now, or None when unknown."""
        if self.available is None:
            return None
        if self.mode == AccountMode.CREDIT:
            return self.available + self.credit_limit
        return self.available


class TopUpMethod(models.TextChoices):
    CARD = "CARD", "Card"
    CRYPTO = "CRYPTO", "Cryptocurrency"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
    RECHARGE_CODE = "RECHARGE_CODE", "Recharge code"
    OTHER = "OTHER", "Other"


class ProviderTopUp(BaseModel):
    """A payment staff made to a provider by hand, recorded for the books.

    Recording one moves no money. It is the operating-expense side of a top-up
    that already happened on the provider's website, kept so the cash-flow view
    can show what the provider balance cost us in cedis.
    """

    account = models.ForeignKey(ProviderAccount, on_delete=models.PROTECT,
                                related_name="top_ups")
    amount = models.DecimalField(max_digits=14, decimal_places=4)
    currency = models.CharField(max_length=3)
    method = models.CharField(max_length=16, choices=TopUpMethod.choices)
    #: The provider's or payment processor's reference. Never a card number.
    external_reference = models.CharField(max_length=120, blank=True, default="")
    #: Cedis paid out of operating funds, when known.
    paid_ghs = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=500, blank=True, default="")

    balance_before = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    frozen_before = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    #: Set when a balance reading after the top-up shows the money arrived.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_balance = models.DecimalField(max_digits=14, decimal_places=4,
                                            null=True, blank=True)
    unconfirmed_alerted_at = models.DateTimeField(null=True, blank=True)

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        db_table = "funding_provider_top_up"
        ordering = ["-created_at"]


class AlertKind(models.TextChoices):
    LOW_BALANCE = "LOW_BALANCE", "Balance below minimum"
    CRITICAL_BALANCE = "CRITICAL_BALANCE", "Balance critical"
    BALANCE_RECOVERED = "BALANCE_RECOVERED", "Balance back above minimum"
    SYNC_FAILED = "SYNC_FAILED", "Balance could not be read"
    API_UNAVAILABLE = "API_UNAVAILABLE", "Provider API unavailable"
    PURCHASE_BLOCKED = "PURCHASE_BLOCKED", "Purchase refused: provider balance too low"
    PROVIDER_REFUSED = "PROVIDER_REFUSED", "Provider refused an order for an account reason"
    FAILURE_SPIKE = "FAILURE_SPIKE", "Spike in failed orders"
    TOP_UP_NOT_REFLECTED = "TOP_UP_NOT_REFLECTED", "Recorded top-up not seen in balance"
    INACTIVITY = "INACTIVITY", "Account close to inactivity deletion"


class AlertSeverity(models.TextChoices):
    INFO = "INFO", "Info"
    WARNING = "WARNING", "Warning"
    CRITICAL = "CRITICAL", "Critical"


class ProviderAlert(BaseModel):
    """Something about a provider account that staff need to know.

    The real reason lives here. Customers only ever see "temporarily
    unavailable".
    """

    provider = models.ForeignKey("catalog.Provider", on_delete=models.CASCADE,
                                 related_name="funding_alerts")
    kind = models.CharField(max_length=24, choices=AlertKind.choices, db_index=True)
    severity = models.CharField(max_length=10, choices=AlertSeverity.choices)
    message = models.CharField(max_length=400)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "funding_provider_alert"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "kind", "created_at"])]
