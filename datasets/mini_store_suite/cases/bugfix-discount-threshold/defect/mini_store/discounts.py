"""Discount rules applied to an order subtotal."""

from __future__ import annotations


def percent_off(amount: float, pct: float) -> float:
    """Return the *discount value* for a percentage off (not the discounted price)."""
    if pct < 0 or pct > 100:
        raise ValueError("pct must be between 0 and 100")
    return round(amount * pct / 100.0, 2)


def bulk_discount(subtotal: float, item_count: int) -> float:
    """Discount value for bulk orders: 10% off when buying 10 or more items.

    The threshold is inclusive — exactly 10 items qualifies.
    """
    if item_count > 10:
        return percent_off(subtotal, 10)
    return 0.0
