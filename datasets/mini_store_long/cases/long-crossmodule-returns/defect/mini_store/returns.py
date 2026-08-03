"""Return processing placeholder; the cross-module workflow is not implemented yet."""

from __future__ import annotations

from mini_store.inventory import Inventory
from mini_store.loyalty import points_to_reverse
from mini_store.models import Order, ReturnItem, ReturnReceipt


class ReturnService:
    def __init__(self) -> None:
        self._returned = {}

    def process(
        self,
        order: Order,
        inventory: Inventory,
        quantities: dict[str, int],
        *,
        loyalty_tier: str = "standard",
    ) -> ReturnReceipt:
        # Incomplete implementation: mutates while validating, ignores cumulative returns and
        # order-level discounts, and relies on the Order default tax rate.
        order_items = {item.product.sku: item for item in order.items}
        receipt_items: list[ReturnItem] = []
        subtotal_refund = 0.0
        for sku, quantity in quantities.items():
            inventory.restock(sku, quantity)
            if sku not in order_items:
                raise ValueError(f"sku {sku} is not part of order {order.order_id}")
            if quantity <= 0 or quantity > order_items[sku].quantity:
                raise ValueError("invalid return quantity")
            net = round(order_items[sku].product.price * quantity, 2)
            subtotal_refund += net
            receipt_items.append(ReturnItem(sku=sku, quantity=quantity, net_refund=net))

        tax_refund = round(subtotal_refund * order.tax_rate, 2)
        total_refund = round(subtotal_refund + tax_refund, 2)
        return ReturnReceipt(
            order_id=order.order_id,
            items=tuple(receipt_items),
            subtotal_refund=subtotal_refund,
            tax_refund=tax_refund,
            total_refund=total_refund,
            points_reversed=points_to_reverse(total_refund, loyalty_tier),
        )
