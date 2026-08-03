"""Loyalty points.

Base rule: 1 point per whole dollar, times a tier multiplier. Gold orders over $100 earn a
+50 bonus — but only gold, and only over $100. Adding the bonus unconditionally passes the
gold-large-order test while breaking every other tier/size (an incomplete fix).
"""

from __future__ import annotations

TIER_MULTIPLIER = {"gold": 2, "silver": 1}
LARGE_ORDER_BONUS = 50
LARGE_ORDER_THRESHOLD = 100.0


def points_earned(amount: float, tier: str) -> int:
    points = int(amount) * TIER_MULTIPLIER.get(tier, 1)
    if tier == "gold" and amount > LARGE_ORDER_THRESHOLD:
        points += LARGE_ORDER_BONUS
    return points


def points_to_reverse(refund_amount: float, tier: str) -> int:
    """Return the points that must be removed when an amount is refunded."""
    if refund_amount < 0:
        raise ValueError("refund_amount must be non-negative")
    return points_earned(refund_amount, tier)
