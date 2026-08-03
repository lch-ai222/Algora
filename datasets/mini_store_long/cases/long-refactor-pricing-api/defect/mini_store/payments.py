"""Payment authorization totals."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def authorization_total(net_amount: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(net_amount, tax_rate)
