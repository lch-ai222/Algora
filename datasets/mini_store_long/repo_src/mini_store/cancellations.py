"""Order cancellation: give the reserved units back, exactly once.

Two guards are needed here and neither substitutes for the other. ``Inventory.release`` refuses
to release more than the SKU pool holds, but the pool is shared: while another order still has
units reserved for the same SKU, a second cancellation of *this* order stays within the pool
and quietly consumes the other order's reservation. Only the caller knows which units were its
own, so cancellation has to be idempotent at this level too.
"""

from __future__ import annotations

from mini_store.inventory import Inventory
from mini_store.models import Order


def cancel_order(order: Order, inventory: Inventory) -> int:
    """Release every line's reservation and return the number of units freed."""
    if order.cancelled:
        raise ValueError(f"order {order.order_id} is already cancelled")

    freed = 0
    for item in order.items:
        inventory.release(item.product.sku, item.quantity)
        freed += item.quantity
    order.cancelled = True
    return freed
