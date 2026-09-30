"""Money helpers.

Every monetary value in this project is a Decimal quantised to 2 places using
ROUND_HALF_UP. Floats are never used for money anywhere.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value) -> Decimal:
    """Coerce to Decimal, rejecting anything that is not a clean number."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # Only ever reached from third-party JSON payloads; go via str so we
        # don't inherit binary float error.
        value = repr(value)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Not a valid monetary amount: {value!r}") from exc


def quantize(value) -> Decimal:
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_to(value, step: Decimal, ceiling: bool = False) -> Decimal:
    """Round `value` to the nearest multiple of `step` (or up, if ceiling)."""
    value = to_decimal(value)
    step = to_decimal(step)
    if step <= 0:
        return quantize(value)
    units = value / step
    rounding = ROUND_CEILING if ceiling else ROUND_HALF_UP
    return quantize((units.quantize(Decimal("1"), rounding=rounding)) * step)


def format_ghs(value) -> str:
    """Money in customer-facing text - notifications, emails, error messages.

    "GH₵ 1,250.00", exactly as the web app writes it (frontend lib/format.ts):
    GH₵ rather than GHS or a bare ₵, a no-break space so the symbol never
    wraps away from the figure, always two decimals.
    """
    return f"GH₵\u00a0{quantize(value):,.2f}"
