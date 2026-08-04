"""Clearance pricing: a fixed markdown applied to end-of-line stock.

Money is rounded in exactly one place — ``discounts.percent_off`` — and every caller
subtracts the value it returns. Rounding again here would paper over a broken primitive.
"""

from __future__ import annotations

from mini_store.discounts import percent_off

CLEARANCE_PCT = 35.0


def clearance_price(list_price: float) -> float:
    return list_price - percent_off(list_price, CLEARANCE_PCT)
