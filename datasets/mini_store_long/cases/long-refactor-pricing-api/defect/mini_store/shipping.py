"""Taxable shipping fee calculations."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def shipping_total(base_fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(base_fee, tax_rate)
