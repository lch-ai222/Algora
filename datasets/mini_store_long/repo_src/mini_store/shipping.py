"""Taxable shipping fee calculations."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def shipping_total(base_fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return taxed_total(base_fee, tax_rate=tax_rate)
