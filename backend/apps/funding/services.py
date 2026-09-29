"""Provider funding: read, grade and guard our prepaid provider balances.

Every provider we have used sells numbers only against money already in our
account there, and none has an API that adds money. TextVerified is funded
with credits bought by card or cryptocurrency (Terms; FAQ "Credits") and
`GET /account/me` only reads the balance. OnlineSim was the same (Terms 4.1,
FAQ "We only have retail sales", `getBalance` read-only). So VerifyGH keeps a
prepaid reserve at the provider, topped up by hand from operating funds. This
module is everything software can honestly do about that:

* read the balance on a schedule and grade it against staff-set levels;
* refuse a purchase *before* charging the customer when the balance cannot
  cover it, and let the order router try another authorised provider;
* tell staff, with the real reason, whenever something needs a person;
* keep the books straight: a top-up is an operating payment recorded here,
  never a movement of customer wallet money.

Nothing here moves money anywhere. See docs/PROVIDER-FUNDING.md.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.accounts.constants import ROLE_PERMISSIONS, AdminPermission
from apps.audit.services import record_admin_action
from apps.common.errors import APIError, ProviderError, ServiceUnavailable, ValidationFailed
from apps.funding.models import (
    AccountMode,
    AlertKind,
    AlertSeverity,
    BalanceStatus,
    ProviderAccount,
    ProviderAlert,
    ProviderTopUp,
    TopUpMethod,
)

logger = logging.getLogger("verifygh.funding")

FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")

#: A reading older than this is shown as stale. The beat task reads every two
#: minutes, so ten means several reads in a row have failed.
STALE_AFTER = timedelta(minutes=10)

#: When a purchase is about to be refused on the cached reading, read the
#: balance live first - unless we already did within this long. Stops a crowd
#: of customers hitting an empty account from becoming a crowd of API calls.
LIVE_RECHECK_INTERVAL = timedelta(seconds=30)

CUSTOMER_UNAVAILABLE = "This service is temporarily unavailable. Please try again shortly."

WALLET_NOT_PROFIT = (
    "Customer wallet balance is not VerifyGH profit. It is money customers have "
    "paid in advance and can still spend, so it is owed to them. Profit is only "
    "what is left of a delivered order's price after the provider's cost."
)


def _cfg(name: str):
    return settings.VERIFYGH[name]


#: What each provider's own published terms say about funding its account.
#: Facts with sources, not settings: change them only when the source changes.
PROVIDER_FUNDING_TERMS = {
    # Terms 4.1 and 11.4/11.5, read 2026-09-29.
    "onlinesim": {"methods": "card, cryptocurrency, bank transfer or recharge code",
                  "deletes_idle_accounts": True},
    # Terms ("Purchases, Cancellation, and Refunds") and FAQ ("Credits"), read
    # 2026-09-29. No inactivity rule is published.
    "textverified": {"methods": "card (via Stripe) or cryptocurrency",
                     "deletes_idle_accounts": False},
}


def _funding_terms(provider) -> dict:
    return PROVIDER_FUNDING_TERMS.get(provider.adapter_key,
                                      {"methods": "", "deletes_idle_accounts": False})


def _decimal(value, name: str, *, minimum: Decimal = ZERO, maximum: Decimal | None = None,
             places: Decimal = FOUR_PLACES) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationFailed(f"{name} must be a number.") from exc
    if not number.is_finite():
        raise ValidationFailed(f"{name} must be a number.")
    if number < minimum:
        raise ValidationFailed(f"{name} cannot be below {minimum}.")
    if maximum is not None and number > maximum:
        raise ValidationFailed(f"{name} cannot be above {maximum}.")
    return number.quantize(places)


def require_reason(reason) -> str:
    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValidationFailed("Give a reason for this change (at least 5 characters).")
    return reason[:500]


# ---------------------------------------------------------------------------
# Accounts and grading
# ---------------------------------------------------------------------------


def account_for(provider) -> ProviderAccount:
    account, _ = ProviderAccount.objects.get_or_create(
        provider=provider,
        defaults={
            "critical_balance": Decimal(str(_cfg("PROVIDER_RESERVE_CRITICAL"))),
            "minimum_balance": Decimal(str(_cfg("PROVIDER_RESERVE_MINIMUM"))),
            "target_balance": Decimal(str(_cfg("PROVIDER_RESERVE_TARGET"))),
        },
    )
    return account


def grade(account: ProviderAccount) -> str:
    spendable = account.spendable
    if spendable is None:
        return BalanceStatus.UNKNOWN
    if spendable <= account.critical_balance:
        return BalanceStatus.CRITICAL
    if spendable < account.minimum_balance:
        return BalanceStatus.LOW
    return BalanceStatus.HEALTHY


def recommended_top_up(account: ProviderAccount) -> Decimal | None:
    """What to add to get back to the target level, rounded up to a whole unit."""
    spendable = account.spendable
    if spendable is None:
        return None
    gap = account.target_balance - spendable
    if gap <= 0:
        return ZERO
    return gap.quantize(Decimal("1"), rounding=ROUND_CEILING)


def _adapter(provider):
    from apps.verification.registry import get_provider

    return get_provider(provider.adapter_key)


def sync_balance(provider) -> ProviderAccount:
    """Read our balance at `provider`, grade it, and alert on any change that matters.

    The network call happens outside any transaction; only the write is locked.
    """
    account = account_for(provider)
    now = timezone.now()
    try:
        adapter = _adapter(provider)
        if not adapter.is_configured:
            # Missing credentials are a setup gap, not an outage: nothing is
            # called, nothing is alerted, and the page says what is missing.
            ProviderAccount.objects.filter(pk=account.pk).update(
                last_sync_attempt_at=now, status=BalanceStatus.UNKNOWN,
                last_sync_error="Not configured: this provider's credentials are not set.",
            )
            account.refresh_from_db()
            return account
        supported = adapter.supports_balance
        reading = adapter.get_balance() if supported else None
    except (ProviderError, ServiceUnavailable) as exc:
        return _record_sync_failure(account, exc, now)

    if not supported or reading is None:
        ProviderAccount.objects.filter(pk=account.pk).update(
            last_sync_attempt_at=now, status=BalanceStatus.UNKNOWN,
            last_sync_error="This provider documents no way to read our balance.",
        )
        account.refresh_from_db()
        return account

    with transaction.atomic():
        account = ProviderAccount.objects.select_for_update().get(pk=account.pk)
        previous = account.status
        previous_spendable = account.spendable
        account.available = Decimal(reading.available).quantize(FOUR_PLACES)
        account.frozen = Decimal(reading.frozen).quantize(FOUR_PLACES)
        account.currency = (reading.currency or account.currency).upper()[:3]
        account.last_synced_at = now
        account.last_sync_attempt_at = now
        account.last_sync_error = ""
        account.consecutive_sync_failures = 0
        account.status = grade(account)
        account.save()

    logger.info("provider_balance_synced", extra={
        "provider": provider.adapter_key, "balance": str(account.available),
        "frozen": str(account.frozen), "status": account.status,
    })
    if account.spendable != previous_spendable:
        # What the marketplace may show depends on this balance.
        refresh_marketplace()
    _alert_on_status_change(account, previous)
    _confirm_top_ups(account)
    return account


def refresh_marketplace() -> None:
    from django.core.cache import cache

    from apps.catalog import marketplace
    from apps.catalog.views import MARKETPLACE_CACHE_KEY

    cache.delete(MARKETPLACE_CACHE_KEY)
    marketplace.invalidate()


def _record_sync_failure(account: ProviderAccount, exc: APIError, now) -> ProviderAccount:
    with transaction.atomic():
        account = ProviderAccount.objects.select_for_update().get(pk=account.pk)
        account.last_sync_attempt_at = now
        account.last_sync_error = (getattr(exc, "message", "") or str(exc))[:255]
        account.consecutive_sync_failures += 1
        account.save(update_fields=["last_sync_attempt_at", "last_sync_error",
                                    "consecutive_sync_failures", "updated_at"])

    provider = account.provider
    code = getattr(exc, "provider_code", "")
    logger.warning("provider_balance_sync_failed", extra={
        "provider": provider.adapter_key, "failures": account.consecutive_sync_failures,
        "provider_code": code,
    })
    if getattr(exc, "operational", False):
        # Blocked account, bad key: nothing will work until a person acts.
        raise_alert(
            provider, AlertKind.API_UNAVAILABLE, AlertSeverity.CRITICAL,
            f"{provider.name} refused our account ({code}). No numbers can be bought "
            "until this is fixed on the provider side.",
            metadata={"provider_code": code},
        )
    elif account.consecutive_sync_failures >= int(_cfg("PROVIDER_SYNC_FAILURE_ALERT_AFTER")):
        raise_alert(
            provider, AlertKind.SYNC_FAILED, AlertSeverity.WARNING,
            f"The {provider.name} balance could not be read "
            f"{account.consecutive_sync_failures} times in a row: {account.last_sync_error}",
            metadata={"failures": account.consecutive_sync_failures},
        )
    return account


def _money(account: ProviderAccount, value) -> str:
    return f"{account.currency} {Decimal(value).quantize(TWO_PLACES)}"


def _alert_on_status_change(account: ProviderAccount, previous: str) -> None:
    provider = account.provider
    status = account.status
    top_up = recommended_top_up(account)
    details = (
        f"{provider.name} balance is {_money(account, account.spendable)} "
        f"(minimum {_money(account, account.minimum_balance)}, "
        f"critical {_money(account, account.critical_balance)}). "
        f"Recommended top-up: {_money(account, top_up or ZERO)}. "
        f"Top up by hand on the {provider.name} website - no API can do it."
    )
    metadata = {"balance": str(account.available), "status": status,
                "recommended_top_up": str(top_up) if top_up is not None else None}
    cooldown = int(_cfg("PROVIDER_ALERT_COOLDOWN_MINUTES"))

    if status == BalanceStatus.CRITICAL:
        # Fires on the way down, then again every few hours until fixed.
        raise_alert(provider, AlertKind.CRITICAL_BALANCE, AlertSeverity.CRITICAL,
                    f"Critical: {details} Purchases that the balance cannot cover are "
                    "being refused.", metadata=metadata,
                    cooldown_minutes=0 if previous != BalanceStatus.CRITICAL else cooldown * 6)
    elif status == BalanceStatus.LOW and previous not in (BalanceStatus.LOW,
                                                           BalanceStatus.CRITICAL):
        raise_alert(provider, AlertKind.LOW_BALANCE, AlertSeverity.WARNING,
                    f"Low: {details}", metadata=metadata)
    elif status == BalanceStatus.HEALTHY and previous in (BalanceStatus.LOW,
                                                           BalanceStatus.CRITICAL):
        raise_alert(provider, AlertKind.BALANCE_RECOVERED, AlertSeverity.INFO,
                    f"{provider.name} balance is back to {_money(account, account.spendable)}.",
                    metadata=metadata, cooldown_minutes=0)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def alert_recipients():
    """Active staff who can act on a provider account (PROVIDER_MANAGE)."""
    from apps.accounts.models import User

    roles = [role for role, permissions in ROLE_PERMISSIONS.items()
             if str(AdminPermission.PROVIDER_MANAGE) in permissions]
    return User.objects.filter(role__in=roles, is_active=True, is_suspended=False)


def raise_alert(provider, kind: str, severity: str, message: str, *,
                metadata: dict | None = None,
                cooldown_minutes: int | None = None) -> ProviderAlert | None:
    """Record an alert and tell staff, at most once per kind per cooldown."""
    if cooldown_minutes is None:
        cooldown_minutes = int(_cfg("PROVIDER_ALERT_COOLDOWN_MINUTES"))
    if cooldown_minutes > 0 and ProviderAlert.objects.filter(
        provider=provider, kind=kind,
        created_at__gte=timezone.now() - timedelta(minutes=cooldown_minutes),
    ).exists():
        return None

    alert = ProviderAlert.objects.create(
        provider=provider, kind=kind, severity=severity, message=message[:400],
        metadata=metadata or {},
    )
    logger.warning("provider_funding_alert", extra={
        "provider": provider.adapter_key, "kind": kind, "severity": severity,
    })

    def _deliver():
        from apps.funding.tasks import deliver_alert

        try:
            deliver_alert.delay(str(alert.id))
        except Exception:
            # No broker: deliver in-process rather than lose the alert.
            logger.warning("provider_alert_queue_unavailable", extra={"kind": kind})
            deliver(alert)

    transaction.on_commit(_deliver)
    return alert


def deliver(alert: ProviderAlert) -> int:
    """Notify every recipient. In-app always; email unless it is only informational."""
    from apps.notifications.models import Channel
    from apps.notifications.services import notify

    channels = (Channel.IN_APP,) if alert.severity == AlertSeverity.INFO else (
        Channel.IN_APP, Channel.EMAIL)
    title = f"{alert.provider.name}: {alert.get_kind_display()}"
    sent = 0
    for user in alert_recipients():
        notify(
            user, event=f"PROVIDER_{alert.kind}", title=title, body=alert.message,
            channels=channels, subject=f"[VerifyGH] {title}",
            metadata={"provider": alert.provider.adapter_key, "alert_id": str(alert.id),
                      "severity": alert.severity},
        )
        sent += 1
    return sent


# ---------------------------------------------------------------------------
# The purchase guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundingCheck:
    ok: bool
    spendable: Decimal | None = None
    required: Decimal | None = None
    currency: str = ""
    reason: str = ""


def required_for(offering) -> Decimal:
    """The most this offering can draw from our balance.

    `getNum` is sent with maxPrice = cost x PROVIDER_PRICE_TOLERANCE, so that is
    the ceiling the balance has to cover.
    """
    tolerance = Decimal(str(_cfg("PROVIDER_PRICE_TOLERANCE")))
    return (Decimal(offering.cost_amount) * tolerance).quantize(FOUR_PLACES)


def _known_short(account: ProviderAccount | None, offering) -> bool:
    """True only when the last reading shows `account` cannot pay for `offering`.

    Anything we cannot tell - no reading, no cost, a currency we cannot
    compare, the guard switched off - is not a known shortfall.
    """
    if not _cfg("PROVIDER_FUNDING_GUARD"):
        return False
    if account is None or account.spendable is None or not offering.cost_amount:
        return False
    if (offering.cost_currency or "").upper() != account.currency.upper():
        return False
    return account.spendable < required_for(offering)


def unfunded_offering_ids(offerings) -> set[str]:
    """Offerings the last balance readings show we cannot pay for.

    For listing only: reads stored balances, never the provider, so browsing
    the marketplace costs no upstream calls. The purchase itself still
    re-reads a low balance live before refusing.
    """
    provider_ids = {offering.provider_id for offering in offerings}
    accounts = {account.provider_id: account for account in
                ProviderAccount.objects.filter(provider_id__in=provider_ids)}
    return {str(offering.pk) for offering in offerings
            if _known_short(accounts.get(offering.provider_id), offering)}


def check_funding(offering, *, live_recheck: bool = True) -> FundingCheck:
    """Can our balance at this offering's provider pay for one number?

    Answers yes whenever it does not know: an unread balance, a currency we
    cannot compare. The provider stays the final judge, and a refusal there is
    still refunded automatically - this guard only exists to stop charging
    customers for purchases we can already see will fail.
    """
    if not _cfg("PROVIDER_FUNDING_GUARD"):
        return FundingCheck(True, reason="guard disabled")
    account = ProviderAccount.objects.filter(provider_id=offering.provider_id).first()
    if account is None or account.spendable is None or not offering.cost_amount:
        return FundingCheck(True, reason="balance unknown")
    if (offering.cost_currency or "").upper() != account.currency.upper():
        logger.warning("provider_funding_currency_mismatch", extra={
            "provider": offering.provider.adapter_key, "cost": offering.cost_currency,
            "balance": account.currency,
        })
        return FundingCheck(True, reason="currency mismatch")

    required = required_for(offering)
    if account.spendable >= required:
        return FundingCheck(True, account.spendable, required, account.currency)

    # The reading may predate a top-up. Look again before turning anyone away.
    recently = account.last_sync_attempt_at and (
        timezone.now() - account.last_sync_attempt_at < LIVE_RECHECK_INTERVAL)
    if live_recheck and not recently:
        account = sync_balance(offering.provider)
        if account.spendable is None or account.spendable >= required:
            return FundingCheck(True, account.spendable, required, account.currency)

    return FundingCheck(
        False, account.spendable, required, account.currency,
        reason=(f"{offering.provider.name} balance {_money(account, account.spendable)} "
                f"cannot cover {offering.service.name} ({offering.country.code}), which "
                f"needs up to {_money(account, required)}."),
    )


def purchase_blocked(offering, check: FundingCheck) -> None:
    """Record why a customer was told "temporarily unavailable"."""
    account = ProviderAccount.objects.filter(provider_id=offering.provider_id).first()
    top_up = recommended_top_up(account) if account else None
    raise_alert(
        offering.provider, AlertKind.PURCHASE_BLOCKED, AlertSeverity.CRITICAL,
        f"A customer could not buy: {check.reason} Customers see \"temporarily "
        f"unavailable\" until the balance is topped up"
        + (f" (recommended: {check.currency} {top_up})." if top_up else "."),
        metadata={"service": offering.service.slug, "country": offering.country.code,
                  "spendable": str(check.spendable), "required": str(check.required)},
    )


def note_provider_failure(provider, exc: Exception) -> None:
    """Called when a provider refuses an order we already charged for (and refunded).

    Account-side refusals (an empty balance, a blocked account) are ours to
    fix, so staff hear about them with the provider's own code, and the
    balance is read again so the guard stops the next customer.
    """
    if not getattr(exc, "operational", False):
        return
    code = getattr(exc, "provider_code", "")
    raise_alert(
        provider, AlertKind.PROVIDER_REFUSED, AlertSeverity.CRITICAL,
        f"{provider.name} refused an order with {code}. The customer was refunded "
        "automatically." + (" Top up the balance." if "BALANCE" in code else ""),
        metadata={"provider_code": code},
    )

    def _refresh():
        from apps.funding.tasks import refresh_provider_balance

        try:
            refresh_provider_balance.delay(str(provider.id))
        except Exception:
            logger.warning("provider_balance_refresh_unqueued",
                           extra={"provider": provider.adapter_key})

    transaction.on_commit(_refresh)


# ---------------------------------------------------------------------------
# Scheduled checks
# ---------------------------------------------------------------------------


def _funded_providers():
    from apps.catalog.models import Provider
    from apps.verification.registry import available_adapters

    return Provider.objects.filter(is_enabled=True, adapter_key__in=available_adapters())


def sync_all() -> dict:
    results = {}
    for provider in _funded_providers():
        try:
            account = sync_balance(provider)
            check_failure_spike(provider)
            check_inactivity(provider, account)
            check_unconfirmed_top_ups(account)
            results[provider.adapter_key] = account.status
        except Exception:
            # One provider's trouble must not stop the others being checked.
            logger.exception("provider_funding_check_failed",
                             extra={"provider": provider.adapter_key})
            results[provider.adapter_key] = "ERROR"
    return results


def check_failure_spike(provider) -> ProviderAlert | None:
    from apps.orders.models import OrderEvent, OrderStatus

    minutes = int(_cfg("PROVIDER_FAILURE_SPIKE_WINDOW_MINUTES"))
    threshold = int(_cfg("PROVIDER_FAILURE_SPIKE_THRESHOLD"))
    failed = OrderEvent.objects.filter(
        status=OrderStatus.FAILED, order__provider=provider,
        created_at__gte=timezone.now() - timedelta(minutes=minutes),
    ).count()
    if failed < threshold:
        return None
    return raise_alert(
        provider, AlertKind.FAILURE_SPIKE, AlertSeverity.WARNING,
        f"{failed} orders failed at {provider.name} in the last {minutes} minutes. "
        "Every one was refunded automatically; check the provider balance and status.",
        metadata={"failed": failed, "window_minutes": minutes},
    )


def last_completed_purchase_at(provider):
    """When the provider last delivered a code to us - a completed, charged purchase."""
    from apps.orders.models import Order

    return (Order.objects.filter(provider=provider, code_received_at__isnull=False)
            .order_by("-code_received_at").values_list("code_received_at", flat=True).first())


def inactivity(provider, account: ProviderAccount) -> dict:
    """Days since the last completed purchase, and the deletion date where the
    provider's terms have one (OnlineSim's do; TextVerified's do not)."""
    last = last_completed_purchase_at(provider)
    deletion_days = int(_cfg("PROVIDER_INACTIVITY_DELETION_DAYS"))
    if last is None:
        return {"last_completed_purchase_at": None, "days_since": None, "deletion_on": None}
    return {
        "last_completed_purchase_at": last,
        "days_since": (timezone.now() - last).days,
        "deletion_on": ((last + timedelta(days=deletion_days)).date()
                        if _funding_terms(provider)["deletes_idle_accounts"] else None),
    }


def check_inactivity(provider, account: ProviderAccount) -> ProviderAlert | None:
    state = inactivity(provider, account)
    if state["deletion_on"] is None or not account.available or account.available <= 0:
        return None
    if state["days_since"] < int(_cfg("PROVIDER_INACTIVITY_WARNING_DAYS")):
        return None
    return raise_alert(
        provider, AlertKind.INACTIVITY, AlertSeverity.WARNING,
        f"No completed purchase at {provider.name} for {state['days_since']} days. Its "
        f"terms delete an account {int(_cfg('PROVIDER_INACTIVITY_DELETION_DAYS'))} days after "
        f"the last completed purchase, and the {_money(account, account.available)} balance "
        f"with it. Complete a purchase before {state['deletion_on']:%d %b %Y}.",
        metadata={"days_since": state["days_since"]}, cooldown_minutes=24 * 60,
    )


def _confirm_top_ups(account: ProviderAccount) -> None:
    if account.available is None or account.last_synced_at is None:
        return
    held_now = account.available + (account.frozen or ZERO)
    for top_up in account.top_ups.filter(confirmed_at__isnull=True,
                                         created_at__lte=account.last_synced_at):
        if top_up.balance_before is None:
            arrived = account.available > 0
        else:
            arrived = held_now > top_up.balance_before + (top_up.frozen_before or ZERO)
        if arrived:
            ProviderTopUp.objects.filter(pk=top_up.pk).update(
                confirmed_at=account.last_synced_at, confirmed_balance=account.available)


def check_unconfirmed_top_ups(account: ProviderAccount) -> list[ProviderAlert]:
    cutoff = timezone.now() - timedelta(hours=int(_cfg("PROVIDER_TOP_UP_CONFIRM_HOURS")))
    alerts = []
    for top_up in account.top_ups.filter(confirmed_at__isnull=True, created_at__lte=cutoff,
                                         unconfirmed_alerted_at__isnull=True):
        alert = raise_alert(
            account.provider, AlertKind.TOP_UP_NOT_REFLECTED, AlertSeverity.WARNING,
            f"A {top_up.currency} {top_up.amount.quantize(TWO_PLACES)} top-up recorded on "
            f"{top_up.created_at:%d %b %Y %H:%M} has not shown up in the "
            f"{account.provider.name} balance. Check the payment with "
            f"{account.provider.name} support.",
            metadata={"top_up_id": str(top_up.id)}, cooldown_minutes=0,
        )
        ProviderTopUp.objects.filter(pk=top_up.pk).update(unconfirmed_alerted_at=timezone.now())
        if alert:
            alerts.append(alert)
    return alerts


# ---------------------------------------------------------------------------
# Staff actions
# ---------------------------------------------------------------------------


def _account_state(account: ProviderAccount) -> dict:
    return {
        "mode": account.mode, "credit_limit": str(account.credit_limit),
        "critical_balance": str(account.critical_balance),
        "minimum_balance": str(account.minimum_balance),
        "target_balance": str(account.target_balance),
    }


def update_account(account: ProviderAccount, *, data: dict, reason, actor,
                   request=None) -> ProviderAccount:
    reason = require_reason(reason)
    with transaction.atomic():
        account = ProviderAccount.objects.select_for_update().get(pk=account.pk)
        before = _account_state(account)
        previous = account.status
        for field, label in (("critical_balance", "Critical level"),
                             ("minimum_balance", "Minimum level"),
                             ("target_balance", "Target level"),
                             ("credit_limit", "Credit limit")):
            if field in data:
                setattr(account, field, _decimal(data[field], label,
                                                 maximum=Decimal("100000")))
        if "mode" in data:
            if data["mode"] not in AccountMode.values:
                raise ValidationFailed("Unknown account mode.")
            account.mode = data["mode"]
        if account.mode == AccountMode.PREPAID:
            account.credit_limit = Decimal("0.0000")
        if not (account.critical_balance <= account.minimum_balance <= account.target_balance):
            raise ValidationFailed(
                "Levels must go critical <= minimum <= target.")
        account.status = grade(account)
        account.save()
        record_admin_action(admin=actor, action="PROVIDER_FUNDING_SETTINGS", target=account,
                            reason=reason, before=before, after=_account_state(account),
                            request=request)
    refresh_marketplace()  # a credit limit changes what can be sold
    _alert_on_status_change(account, previous)
    return account


_DIGIT_RUN = re.compile(r"\d[\d \-]{11,}\d")


def _looks_like_card_number(text: str) -> bool:
    """A Luhn-valid run of 13-19 digits: almost certainly a card number."""
    for match in _DIGIT_RUN.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if not 13 <= len(digits) <= 19:
            continue
        total = 0
        for index, char in enumerate(reversed(digits)):
            number = int(char)
            if index % 2:
                number *= 2
                if number > 9:
                    number -= 9
            total += number
        if total % 10 == 0:
            return True
    return False


def record_top_up(account: ProviderAccount, *, data: dict, actor,
                  request=None) -> ProviderTopUp:
    """Record a top-up staff already paid on the provider's website.

    Moves no money and touches no wallet. It then reads the balance, so the
    record shows whether the money has arrived.
    """
    amount = _decimal(data.get("amount"), "Amount", minimum=Decimal("0.01"),
                      maximum=Decimal("100000"))
    currency = str(data.get("currency") or account.currency).upper()[:3]
    if currency != account.currency.upper():
        raise ValidationFailed(
            f"This account holds {account.currency}; record the amount credited in "
            f"{account.currency}.")
    method = str(data.get("method") or "")
    if method not in TopUpMethod.values:
        raise ValidationFailed("Choose how the top-up was paid.")
    reference = str(data.get("external_reference") or "").strip()[:120]
    note = str(data.get("note") or "").strip()[:500]
    for text in (reference, note):
        if _looks_like_card_number(text):
            raise ValidationFailed(
                "That looks like a card number. Never record card details - use the "
                "payment or transaction reference instead.")
    paid_ghs = None
    if data.get("paid_ghs") not in (None, ""):
        paid_ghs = _decimal(data["paid_ghs"], "Cedis paid", maximum=Decimal("10000000"),
                            places=TWO_PLACES)

    with transaction.atomic():
        top_up = ProviderTopUp.objects.create(
            account=account, amount=amount, currency=currency, method=method,
            external_reference=reference, paid_ghs=paid_ghs, note=note,
            balance_before=account.available, frozen_before=account.frozen, recorded_by=actor,
        )
        record_admin_action(
            admin=actor, action="PROVIDER_TOP_UP_RECORDED", target=top_up,
            reason=note or f"{account.provider.name} top-up recorded",
            after={"amount": str(amount), "currency": currency, "method": method,
                   "external_reference": reference,
                   "paid_ghs": str(paid_ghs) if paid_ghs is not None else None,
                   "balance_before": str(account.available)},
            request=request,
        )
    try:
        sync_balance(account.provider)
    except Exception:
        logger.exception("provider_balance_sync_after_top_up_failed")
    top_up.refresh_from_db()
    return top_up


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fx(currency: str) -> Decimal | None:
    from apps.pricing.engine import pricing_fx

    try:
        return pricing_fx(currency).rate
    except APIError:
        return None


def usage(provider, days: int = 30) -> dict:
    """What we actually spent at the provider, from our own order records."""
    from apps.orders.models import Order

    since = timezone.now() - timedelta(days=days)
    delivered = Order.objects.filter(provider=provider, code_received_at__gte=since)
    count = delivered.count()
    spent = delivered.aggregate(total=Sum("provider_cost"))["total"] or ZERO
    week = Order.objects.filter(provider=provider,
                                code_received_at__gte=timezone.now() - timedelta(days=7))
    spent_7d = week.aggregate(total=Sum("provider_cost"))["total"] or ZERO
    return {
        "delivered": count,
        "spent": Decimal(spent),
        "average_cost": (Decimal(spent) / count).quantize(FOUR_PLACES) if count else None,
        "daily_burn": (Decimal(spent_7d) / 7).quantize(FOUR_PLACES),
    }


def account_report(account: ProviderAccount) -> dict:
    provider = account.provider
    used = usage(provider)
    spendable = account.spendable
    average = used["average_cost"]
    if average is None:
        from apps.catalog.marketplace import sellable_offerings

        costs = sorted(Decimal(o.cost_amount) for o in sellable_offerings()
                       if o.provider_id == provider.id and o.cost_amount)
        average = costs[len(costs) // 2] if costs else None
    now = timezone.now()
    return {
        "provider": provider.name,
        "adapter_key": provider.adapter_key,
        "mode": account.mode,
        "currency": account.currency,
        "balance": _str(account.available),
        "frozen": _str(account.frozen),
        "credit_limit": _str(account.credit_limit),
        "spendable": _str(spendable),
        "critical_balance": _str(account.critical_balance),
        "minimum_balance": _str(account.minimum_balance),
        "target_balance": _str(account.target_balance),
        "status": account.status,
        "recommended_top_up": _str(recommended_top_up(account)),
        "last_synced_at": account.last_synced_at,
        "last_sync_attempt_at": account.last_sync_attempt_at,
        "last_sync_error": account.last_sync_error,
        "consecutive_sync_failures": account.consecutive_sync_failures,
        "stale": account.last_synced_at is None or now - account.last_synced_at > STALE_AFTER,
        "delivered_30d": used["delivered"],
        "spent_30d": _str(used["spent"]),
        "average_cost": _str(average),
        "estimated_purchases_left": (int(spendable // average)
                                     if spendable is not None and average else None),
        "daily_burn": _str(used["daily_burn"]),
        "days_of_cover": (int(spendable // used["daily_burn"])
                          if spendable is not None and used["daily_burn"] else None),
        **inactivity(provider, account),
        "supports_account_funding": False,
        "funding_instructions": (
            f"{provider.name} is prepaid and has no funding API. Top up by hand in the "
            f"{provider.name} web account"
            + (f" ({_funding_terms(provider)['methods']})" if _funding_terms(provider)["methods"]
               else "")
            + ", then record the top-up here."),
        "guard_enabled": bool(_cfg("PROVIDER_FUNDING_GUARD")),
    }


def _str(value) -> str | None:
    return None if value is None else str(Decimal(value).quantize(FOUR_PLACES))


def _ghs(value) -> str:
    return str(Decimal(value or 0).quantize(TWO_PLACES))


def cash_flow() -> dict:
    """Customer money, our money at providers, and what we actually earned - kept apart."""
    from apps.orders.models import ACTIVE_ORDER_STATUSES, Order
    from apps.wallet.models import Wallet

    money = DecimalField(max_digits=18, decimal_places=6)
    wallets = Wallet.objects.aggregate(cash=Sum("balance"), promo=Sum("promo_balance"))
    cash = Decimal(wallets["cash"] or 0)
    promo = Decimal(wallets["promo"] or 0)
    in_progress = Decimal(Order.objects.filter(status__in=ACTIVE_ORDER_STATUSES)
                          .aggregate(total=Sum("price"))["total"] or 0)

    def earned(queryset):
        totals = queryset.aggregate(
            revenue=Sum("price"),
            cost=Sum(ExpressionWrapper(F("provider_cost") * F("exchange_rate"),
                                       output_field=money)),
        )
        revenue = Decimal(totals["revenue"] or 0)
        cost = Decimal(totals["cost"] or 0)
        return revenue, cost

    delivered = Order.objects.filter(code_received_at__isnull=False)
    since = timezone.now() - timedelta(days=30)
    revenue_30, cost_30 = earned(delivered.filter(code_received_at__gte=since))
    revenue_all, cost_all = earned(delivered)

    provider_ghs = ZERO
    needed_ghs = ZERO
    unconverted = []
    unread = []
    accounts = {account.provider_id: account for account in ProviderAccount.objects.filter(
        provider__in=_funded_providers())}
    for provider in _funded_providers():
        account = accounts.get(provider.id)
        if account is None:
            # Never synced: as unknown as an unread balance, not zero.
            unread.append(provider.name)
            continue
        rate = _fx(account.currency)
        spendable = account.spendable
        if spendable is None:
            unread.append(provider.name)
        top_up = recommended_top_up(account)
        if rate is None:
            unconverted.append(account.currency)
        else:
            provider_ghs += (spendable or ZERO) * rate
            needed_ghs += (top_up or ZERO) * rate
    top_ups = ProviderTopUp.objects.all()
    top_up_ghs = Decimal(top_ups.aggregate(total=Sum("paid_ghs"))["total"] or 0)
    top_up_30 = Decimal(top_ups.filter(created_at__gte=since)
                        .aggregate(total=Sum("paid_ghs"))["total"] or 0)

    # If every customer spent their balance today, roughly what would the
    # provider charge us? Uses the cost share of delivered revenue so far.
    cost_share = (cost_all / revenue_all) if revenue_all else None
    cost_to_serve = (cash + promo) * cost_share if cost_share is not None else None
    # Unknowable while any balance is unread or unconverted: treating those as
    # zero would report a shortfall that may not exist.
    shortfall = (max(ZERO, cost_to_serve - provider_ghs)
                 if cost_to_serve is not None and not unread and not unconverted else None)

    return {
        "currency": "GHS",
        "customer_funds": {
            "wallet_cash": _ghs(cash),
            "wallet_promotional": _ghs(promo),
            "orders_in_progress": _ghs(in_progress),
            "note": "Owed to customers. Not revenue, not profit, and never used to pay "
                    "a provider directly.",
        },
        "provider_balance_ghs": _ghs(provider_ghs),
        "provider_balance_unconverted": unconverted,
        "provider_balance_unread": unread,
        "reserve_top_up_needed_ghs": _ghs(needed_ghs),
        "estimated_cost_to_serve_wallets_ghs": (_ghs(cost_to_serve)
                                                if cost_to_serve is not None else None),
        "estimated_shortfall_ghs": _ghs(shortfall) if shortfall is not None else None,
        "earnings_30d": {"revenue": _ghs(revenue_30), "provider_cost": _ghs(cost_30),
                         "gross_profit": _ghs(revenue_30 - cost_30)},
        "earnings_all_time": {"revenue": _ghs(revenue_all), "provider_cost": _ghs(cost_all),
                              "gross_profit": _ghs(revenue_all - cost_all)},
        "top_ups_paid_ghs": {"last_30d": _ghs(top_up_30), "all_time": _ghs(top_up_ghs)},
        "wallet_is_not_profit": WALLET_NOT_PROFIT,
    }
