"""Bundle discounts (tiered by item count).

3+ items get 5% off; 5+ items get 10% off. The tiers are the trap: bumping the single rate to
10% passes the 5-item test but breaks the 3-item tier — an over-broad fix caught only by the
tier regression test.
"""

from __future__ import annotations

from mini_store.discounts import percent_off


def bundle_price(items_total: float, num_items: int) -> float:
    if num_items >= 5:
        discount = percent_off(items_total, 10)
    elif num_items >= 3:
        discount = percent_off(items_total, 5)
    else:
        discount = 0.0
    return round(items_total - discount, 2)
