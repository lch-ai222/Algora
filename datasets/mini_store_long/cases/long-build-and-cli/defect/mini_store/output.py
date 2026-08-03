"""Stable structured output contracts used by automation."""

from __future__ import annotations


def quote_payload(amount: float, items: int, *, tax_rate: float) -> dict[str, float | int]:
    discount = 0.0
    tax = tax_rate
    return {
        "amount": amount,
        "items": items,
        "discount": discount,
        "tax": tax,
        "total": round(amount + tax, 2),
    }
