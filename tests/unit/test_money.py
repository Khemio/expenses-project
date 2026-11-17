
from decimal import Decimal

import pytest

from app.services.money import to_cents


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("0", 0),
        ("0.01", 1),
        ("999.99", 99999),
        ("1000.00", 100000),
        ("1000.01", 100001),
        (Decimal("125.50"), 12550),
        (-1, -100),
    ],
)
def test_exact_conversion(amount, expected):
    assert to_cents(amount) == expected


@pytest.mark.parametrize(
    "amount",
    [
        "1.234",
        "NaN",
        "Infinity",
        "not-a-number",
        0.1,
        True,
    ],
)
def test_invalid_conversion(amount):
    with pytest.raises(ValueError):
        to_cents(amount)
