"""Stable structured output contracts used by automation."""

from __future__ import annotations

from mini_store.discounts import bulk_discount
from mini_store.pricing import tax_amount


def quote_payload(amount: float, items: int, *, tax_rate: float) -> dict[str, float | int]:
    discount = bulk_discount(amount, items)
    net = round(amount - discount, 2)
    tax = tax_amount(net, tax_rate=tax_rate)
    return {
        "amount": amount,
        "items": items,
        "discount": discount,
        "tax": tax,
        "total": round(net + tax, 2),
    }
