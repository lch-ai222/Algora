"""Member discounts, tiered by membership level."""

from __future__ import annotations

from mini_store.discounts import percent_off

TIER_PCT = {"basic": 0.0, "plus": 5.0, "premier": 12.5}


def member_discount(subtotal: float, tier: str) -> float:
    """Discount value for a member tier. Unknown tiers earn nothing."""
    return percent_off(subtotal, TIER_PCT.get(tier, 0.0))
