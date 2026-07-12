"""Order placement — the cross-module workflow: cart → inventory → discounts → pricing.

``place_order`` is intentionally unimplemented (a spec task): the tests describe the
required behavior and an agent must implement it.
"""

from __future__ import annotations

from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Order


def place_order(order_id: str, cart: Cart, inventory: Inventory, tax_rate: float | None = None) -> Order:
    """Reserve stock for every cart line, then price the order.

    Behavior the implementation must satisfy:
    - Reserve each line's quantity in ``inventory`` (raising ValueError if any line lacks
      available stock — and reserving nothing if it can't be fully fulfilled).
    - Compute ``subtotal`` from the cart, apply ``bulk_discount`` on item count, then apply
      sales tax (use ``DEFAULT_TAX_RATE`` unless ``tax_rate`` is given) to the discounted amount.
    - Return an ``Order`` with items, subtotal, discount, tax, and total populated.
    """
    raise NotImplementedError("place_order is not implemented yet")
