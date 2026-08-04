"""Flash sales: a percentage off that stacks on top of an already discounted price.

Like every other caller, this relies on ``discounts.percent_off`` to return a cents-rounded
value rather than rounding again itself.
"""

from __future__ import annotations

from mini_store.discounts import percent_off


def flash_price(current_price: float, pct: float) -> float:
    return current_price - percent_off(current_price, pct)
