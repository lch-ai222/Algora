"""Coupon redemption. A coupon is a percentage off the eligible subtotal."""

from __future__ import annotations

from dataclasses import dataclass

from mini_store.discounts import percent_off


@dataclass(frozen=True)
class Coupon:
    code: str
    pct: float


def redeem(coupon: Coupon, eligible_subtotal: float) -> float:
    """Return the amount the coupon takes off ``eligible_subtotal``."""
    if eligible_subtotal < 0:
        raise ValueError("eligible_subtotal must not be negative")
    return percent_off(eligible_subtotal, coupon.pct)
