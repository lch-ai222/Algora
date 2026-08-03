"""Marketplace settlement pricing."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def buyer_total(item_total: float, platform_fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(round(item_total + platform_fee, 2), tax_rate)
