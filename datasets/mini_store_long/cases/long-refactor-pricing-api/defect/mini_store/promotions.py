"""Promotional-order pricing."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def promotional_total(net_amount: float, credit: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    if credit < 0 or credit > net_amount:
        raise ValueError("credit must be between zero and net_amount")
    return apply_tax(round(net_amount - credit, 2), tax_rate)
