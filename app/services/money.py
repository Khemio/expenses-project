
from decimal import Decimal, InvalidOperation


def to_cents(amount: Decimal | int | str) -> int:
    """Convert a monetary amount to exact integer cents.

    Reject amounts that cannot be represented exactly
    with two decimal places.
    """
    if isinstance(amount, float) or isinstance(amount, bool):
        raise ValueError(
            "Monetary values must use Decimal, int, or str"
        )

    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary amount") from exc

    if not value.is_finite():
        raise ValueError("Monetary amount must be finite")

    cents = value * 100

    if cents != cents.to_integral_value():
        raise ValueError(
            "Monetary amount has fractional cents"
        )

    result = int(cents)

    if not -(2**63) <= result < 2**63:
        raise ValueError("Monetary amount exceeds integer range")

    return result
