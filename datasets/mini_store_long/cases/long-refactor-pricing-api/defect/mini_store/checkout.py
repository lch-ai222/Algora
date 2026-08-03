"""Read-only cart checkout estimates."""

from __future__ import annotations

from mini_store.cart import Cart
from mini_store.pricing import DEFAULT_TAX_RATE, apply_tax


def checkout_total(cart: Cart, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return apply_tax(cart.subtotal(), tax_rate)
