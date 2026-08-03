"""Order placement — the cross-module workflow: cart → inventory → discounts → pricing."""

from __future__ import annotations

from mini_store.cart import Cart
from mini_store.discounts import bulk_discount
from mini_store.inventory import Inventory
from mini_store.models import Order
from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def place_order(order_id: str, cart: Cart, inventory: Inventory, tax_rate: float | None = None) -> Order:
    """Reserve stock for every cart line, then price the order.

    - Reserve each line's quantity in ``inventory`` (raising ValueError if any line lacks
      available stock — reserving nothing if it can't be fully fulfilled).
    - Compute ``subtotal`` from the cart, apply ``bulk_discount`` on item count, then apply
      sales tax (``DEFAULT_TAX_RATE`` unless ``tax_rate`` given) to the discounted amount.
    - Return an ``Order`` with items, subtotal, discount, tax, and total populated.
    """
    rate = DEFAULT_TAX_RATE if tax_rate is None else tax_rate
    items = cart.items()

    inventory.reserve_many((item.product.sku, item.quantity) for item in items)

    sub = cart.subtotal()
    discount = bulk_discount(sub, cart.item_count())
    discounted = round(sub - discount, 2)
    total = taxed_total(discounted, tax_rate=rate)
    tax = round(total - discounted, 2)
    return Order(
        order_id=order_id,
        items=items,
        subtotal=sub,
        discount=discount,
        tax=tax,
        total=total,
        tax_rate=rate,
    )
