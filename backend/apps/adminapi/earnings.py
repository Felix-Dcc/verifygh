"""What the business earned, in one place, for every dashboard that reports it.

Three things are sold: verification orders, number rentals and extensions of a
rental. Only what the customer received counts - a delivered code, a number
handed over, time actually added - and from that, money given back:

* A refund on a delivered order (staff goodwill on a CODE_RECEIVED order, or an
  upheld number-issue report on a COMPLETED one) leaves the order's status where
  it was, so counting `price` alone kept the refunded cedis in revenue. Revenue
  is the price less any completed refund.
* Provider cost stays - we still paid it - unless the provider refunded us for
  that verification (`provider_refund_accepted`).

Rentals and extensions need no netting here: a refunded rental leaves the
delivered statuses, and an extension is only refunded when it FAILED.
"""

from __future__ import annotations

from django.db.models import Case, DecimalField, ExpressionWrapper, F, Q, Value, When

from apps.orders.models import Order, OrderStatus, RefundStatus

MONEY = DecimalField(max_digits=18, decimal_places=4)

#: Provider cost in GHS, from the rate frozen on each row. Orders, rentals and
#: rental extensions all carry `provider_cost` and `exchange_rate`.
COST_IN_GHS = ExpressionWrapper(F("provider_cost") * F("exchange_rate"), output_field=MONEY)

#: Orders that earned revenue: the customer got (or is reading) their code.
EARNING = [OrderStatus.COMPLETED, OrderStatus.CODE_RECEIVED]

_REFUNDED = Q(refund__status=RefundStatus.COMPLETED)

_ORDER_REVENUE = ExpressionWrapper(
    F("price") - Case(When(_REFUNDED, then=F("refund__amount")),
                      default=Value(0), output_field=MONEY),
    output_field=MONEY,
)
_ORDER_COST = ExpressionWrapper(
    COST_IN_GHS - Case(When(_REFUNDED & Q(refund__provider_refund_accepted=True),
                            then=COST_IN_GHS),
                       default=Value(0), output_field=MONEY),
    output_field=MONEY,
)


def revenue_of(model):
    """The expression to Sum for revenue on rows of `model`."""
    return _ORDER_REVENUE if model is Order else F("price")


def cost_of(model):
    """The expression to Sum for provider cost (GHS) on rows of `model`."""
    return _ORDER_COST if model is Order else COST_IN_GHS


def earning_rows(*window, **when):
    """(orders, rentals, extensions) that earned revenue, each a queryset.

    `window` (Q objects) and `when` filter each on its own fields, e.g.
    created_at__date=today.
    """
    from apps.rentals.models import (
        DELIVERED_RENTAL_STATUSES,
        ExtensionStatus,
        Rental,
        RentalExtension,
    )

    return (
        Order.objects.filter(*window, status__in=EARNING, **when),
        Rental.objects.filter(*window, status__in=DELIVERED_RENTAL_STATUSES, **when),
        RentalExtension.objects.filter(*window, status=ExtensionStatus.COMPLETED, **when),
    )
