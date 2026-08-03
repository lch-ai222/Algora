"""Gift-card purchase totals."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def gift_card_total(value: float, activation_fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(round(value + activation_fee, 2), tax_rate)
