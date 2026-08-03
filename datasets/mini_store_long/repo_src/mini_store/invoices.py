"""Invoice calculations using the V3 keyword-only pricing API."""

from __future__ import annotations

from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def invoice_total(net_amount: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return taxed_total(net_amount, tax_rate=tax_rate)
