"""Exact finite Decimal addition/subtraction independent of caller context."""
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext


def money_sum(values):
    values = tuple(values)
    if not values:
        return Decimal('0')
    precision = max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + len(str(len(values))) + 2
    with localcontext(Context(prec=max(1, precision), Emax=MAX_EMAX, Emin=MIN_EMIN)):
        return sum(values, Decimal('0'))


def money_difference(value, *debits):
    # copy_negate is exact and does not inherit the active context.
    return money_sum((value, *(item.copy_negate() for item in debits)))
