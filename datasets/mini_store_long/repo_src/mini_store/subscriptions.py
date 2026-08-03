"""Subscription renewal pricing."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def renewal_total(monthly_price: float, months: int, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    if months <= 0:
        raise ValueError("months must be positive")
    return taxed_total(round(monthly_price * months, 2), tax_rate=tax_rate)
