"""Agents: cash commission on what an agent's referred customers buy.

Commission is never written from inside a purchase or a refund. `sync` reads
the sales that already exist and brings the commission rows up to date: a row
for each delivered, unrefunded, cash-paid sale by a customer the agent
referred, and a reversal for any row whose sale was refunded afterwards. It is
idempotent - the unique (kind, source) constraint allows one row per sale - and
runs whenever commission is read or an agent is changed, so the money paths in
orders and rentals stay exactly as they were.

What an agent is owed is the EARNED rows less the payouts staff recorded.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.adminapi.earnings import EARNING
from apps.audit.services import record_admin_action
from apps.common.errors import Conflict, ValidationFailed
from apps.common.money import format_ghs, quantize
from apps.orders.models import Order
from apps.referrals.models import (
    Agent,
    AgentCommission,
    AgentPayout,
    CommissionKind,
    CommissionStatus,
    Referral,
    ReferralStatus,
    RiskKind,
)
from apps.rentals.models import (
    DELIVERED_RENTAL_STATUSES,
    ExtensionStatus,
    Rental,
    RentalExtension,
)

logger = logging.getLogger("verifygh.agents")

ZERO = Decimal("0.00")

#: Sign-up evidence that the "customer" is the agent: no commission on an
#: agent's own second account. A referral staff rejected earns nothing either.
#: The other flags (a busy hour, a shared shop phone) are not about identity
#: and do not stop commission.
_SAME_PERSON = [RiskKind.SHARED_EMAIL, RiskKind.EMAIL_ALIAS, RiskKind.SHARED_PHONE,
                RiskKind.SHARED_DEVICE]


def default_percent() -> Decimal:
    return quantize(settings.VERIFYGH["AGENT_COMMISSION_PERCENT"])


def _sales(kind: str):
    """(queryset of sales that still stand, lookup to the buyer, reference field)."""
    if kind == CommissionKind.ORDER:
        # A refund on a delivered order leaves its status alone, hence the amount.
        return (Order.objects.filter(status__in=EARNING, refunded_amount=ZERO),
                "user", "reference")
    if kind == CommissionKind.RENTAL:
        return (Rental.objects.filter(status__in=DELIVERED_RENTAL_STATUSES),
                "user", "reference")
    return (RentalExtension.objects.filter(status=ExtensionStatus.COMPLETED),
            "rental__user", "rental__reference")


def _lock(agent: Agent) -> Agent:
    return Agent.objects.select_for_update().get(pk=agent.pk)


@transaction.atomic
def sync(agent: Agent) -> None:
    """Bring one agent's commission rows up to date with their customers' sales."""
    agent = _lock(agent)

    for kind in CommissionKind.values:
        standing, buyer, reference = _sales(kind)

        earned = AgentCommission.objects.filter(
            agent=agent, kind=kind, status=CommissionStatus.EARNED)
        still_standing = standing.filter(pk__in=earned.values("source_id")).values("pk")
        earned.exclude(source_id__in=still_standing).update(
            status=CommissionStatus.REVERSED, reversed_at=timezone.now())

        if not agent.is_active:
            continue
        customers = (Referral.objects.filter(referrer=agent.user_id)
                     .exclude(status=ReferralStatus.REJECTED)
                     .exclude(risk_flags__kind__in=_SAME_PERSON).values("referred_user"))
        new_sales = (
            standing.filter(**{f"{buyer}__in": customers},
                            created_at__gte=agent.active_since, cash_amount__gt=ZERO)
            .exclude(pk__in=AgentCommission.objects.filter(kind=kind).values("source_id"))
            .values_list("pk", f"{buyer}_id", reference, "cash_amount")
        )
        AgentCommission.objects.bulk_create(
            [
                AgentCommission(
                    agent=agent, customer_id=customer_id, kind=kind, source_id=pk,
                    source_reference=source_reference, base_amount=cash,
                    percent=agent.commission_percent,
                    amount=quantize(cash * agent.commission_percent / Decimal("100")),
                )
                for pk, customer_id, source_reference, cash in new_sales
            ],
            # Two syncs at once would each see the sale as new; the constraint
            # keeps one row.
            ignore_conflicts=True,
        )


def sync_all() -> None:
    for agent in Agent.objects.all():
        sync(agent)


def totals(agent: Agent) -> dict:
    """What the agent earned, was paid and is still owed. Call `sync` first."""
    rows = AgentCommission.objects.filter(agent=agent, status=CommissionStatus.EARNED)
    figures = rows.aggregate(earned=Sum("amount"), sales=Count("pk"), volume=Sum("base_amount"))
    earned = figures["earned"] or ZERO
    paid = AgentPayout.objects.filter(agent=agent).aggregate(total=Sum("amount"))["total"] or ZERO
    return {
        "customers": Referral.objects.filter(referrer=agent.user_id).count(),
        "sales": figures["sales"],
        "sales_volume": str(quantize(figures["volume"] or ZERO)),
        "earned": str(quantize(earned)),
        "paid": str(quantize(paid)),
        # Negative when a paid-for sale was refunded later: it comes off the
        # agent's next earnings.
        "balance": str(quantize(earned - paid)),
    }


def _check_percent(percent) -> Decimal:
    percent = quantize(percent)
    if percent < ZERO or percent > Decimal("50.00"):
        raise ValidationFailed("Commission must be between 0% and 50%.")
    return percent


def _tell(user, title: str, body: str) -> None:
    from apps.notifications.models import NotificationEvent
    from apps.notifications.services import notify

    notify(user, event=NotificationEvent.ADMIN_MESSAGE, title=title, body=body,
           metadata={"link": "/agent"})


@transaction.atomic
def register(*, user, percent=None, payout_details: str = "", admin, request=None) -> Agent:
    if Agent.objects.filter(user=user).exists():
        raise Conflict("That person is already an agent.")
    if user.is_suspended or not user.is_active:
        raise Conflict("A suspended account cannot be an agent.")
    percent = default_percent() if percent in (None, "") else _check_percent(percent)

    agent = Agent.objects.create(
        user=user, commission_percent=percent, active_since=timezone.now(),
        payout_details=payout_details.strip()[:120], created_by=admin,
    )
    record_admin_action(
        admin=admin, action="AGENT_REGISTER", target=agent, reason="Registered as an agent",
        after={"user": str(user.pk), "commission_percent": str(percent)}, request=request,
    )
    _tell(user, "You are now a VerifyGH agent",
          f"You earn {percent}% of what your customers pay for numbers. Share your link "
          "from the Agent page.")
    return agent


@transaction.atomic
def update(agent: Agent, *, percent=None, is_active=None, payout_details=None,
           admin, request=None) -> Agent:
    # Settle everything sold so far at the old rate and the old on/off state first.
    sync(agent)
    agent = _lock(agent)
    before = {"commission_percent": str(agent.commission_percent),
              "is_active": agent.is_active, "payout_details": agent.payout_details}

    if percent is not None:
        agent.commission_percent = _check_percent(percent)
    if payout_details is not None:
        agent.payout_details = str(payout_details).strip()[:120]
    if is_active is not None and bool(is_active) != agent.is_active:
        agent.is_active = bool(is_active)
        if agent.is_active:
            agent.active_since = timezone.now()
    agent.save()

    record_admin_action(
        admin=admin, action="AGENT_UPDATE", target=agent, reason="Agent details changed",
        before=before,
        after={"commission_percent": str(agent.commission_percent),
               "is_active": agent.is_active, "payout_details": agent.payout_details},
        request=request,
    )
    return agent


@transaction.atomic
def record_payout(agent: Agent, *, amount, reference: str, note: str = "",
                  admin, request=None) -> AgentPayout:
    """Record commission staff already sent by mobile money. Moves no money itself."""
    sync(agent)
    agent = _lock(agent)
    amount = quantize(amount)
    reference = reference.strip()
    if amount <= ZERO:
        raise ValidationFailed("Enter the amount you sent.")
    if not reference:
        raise ValidationFailed("Enter the mobile money transaction ID.")
    owed = Decimal(totals(agent)["balance"])
    if amount > owed:
        raise ValidationFailed(f"That is more than the {format_ghs(owed)} this agent is owed.")

    payout = AgentPayout.objects.create(
        agent=agent, amount=amount, reference=reference[:80], note=note.strip()[:255],
        paid_by=admin,
    )
    record_admin_action(
        admin=admin, action="AGENT_PAYOUT", target=agent,
        reason=note.strip() or "Commission paid by mobile money",
        before={"balance": str(owed)},
        after={"amount": str(amount), "reference": payout.reference,
               "balance": str(quantize(owed - amount))},
        request=request,
    )
    logger.info("agent_payout_recorded", extra={"agent": str(agent.pk), "amount": str(amount)})
    _tell(agent.user, f"Commission paid: {format_ghs(amount)}",
          f"We sent {format_ghs(amount)} to your mobile money. Transaction ID: "
          f"{payout.reference}.")
    return payout
