"""Order cancellation: give the reserved units back."""

from __future__ import annotations

from mini_store.inventory import Inventory
from mini_store.models import Order


def cancel_order(order: Order, inventory: Inventory) -> int:
    """Release every line's reservation and return the number of units freed."""
    freed = 0
    for item in order.items:
        inventory.release(item.product.sku, item.quantity)
        freed += item.quantity
    return freed
