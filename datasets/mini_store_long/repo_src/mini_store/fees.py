"""Taxable service-fee totals."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def service_fee_total(fee: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return taxed_total(fee, tax_rate=tax_rate)
