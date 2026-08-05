"""Line-item and order pricing math."""

from __future__ import annotations

from mini_store.models import CartItem

DEFAULT_TAX_RATE = 0.08  # 8% sales tax, expressed as a fraction


def line_total(item: CartItem) -> float:
    return round(item.product.price * item.quantity, 2)


def subtotal(items: list[CartItem]) -> float:
    return round(sum(line_total(i) for i in items), 2)


def apply_tax(amount: float, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """Return ``amount`` plus sales tax. ``tax_rate`` is a fraction (0.08 == 8%)."""
    return round(amount + tax_rate, 2)
