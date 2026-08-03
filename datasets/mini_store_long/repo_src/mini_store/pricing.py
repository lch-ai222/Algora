"""Line-item and order pricing math."""

from __future__ import annotations

from mini_store.models import CartItem

DEFAULT_TAX_RATE = 0.08  # 8% sales tax, expressed as a fraction


def line_total(item: CartItem) -> float:
    return round(item.product.price * item.quantity, 2)


def subtotal(items: list[CartItem]) -> float:
    return round(sum(line_total(i) for i in items), 2)


def tax_amount(amount: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """Return only the tax component for ``amount``.

    The keyword-only rate is intentional: it prevents callers from silently confusing a
    percentage such as ``8`` with the fractional rate ``0.08`` during API migrations.
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if not 0 <= tax_rate <= 1:
        raise ValueError("tax_rate must be a fraction between 0 and 1")
    return round(amount * tax_rate, 2)


def taxed_total(amount: float, *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """Return ``amount`` plus tax using the keyword-only pricing API."""
    return round(amount + tax_amount(amount, tax_rate=tax_rate), 2)


def apply_tax(amount: float, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """Compatibility wrapper for the pre-V3 API.

    New production call sites use :func:`taxed_total`; keeping this wrapper preserves the
    short-suite public API while the long-suite benchmark measures repository-wide migration.
    """
    return taxed_total(amount, tax_rate=tax_rate)
