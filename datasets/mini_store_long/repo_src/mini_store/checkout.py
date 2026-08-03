"""Read-only cart checkout estimates."""

from __future__ import annotations

from mini_store.cart import Cart
from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def checkout_total(cart: Cart, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return taxed_total(cart.subtotal(), tax_rate=tax_rate)
