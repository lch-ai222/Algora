"""Taxable service-fee totals."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def service_fee_total(fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(fee, tax_rate)
