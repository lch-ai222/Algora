"""Atomic, stateful return processing across orders, inventory, and loyalty."""

from __future__ import annotations

from mini_store.inventory import Inventory
from mini_store.loyalty import points_to_reverse
from mini_store.models import Order, ReturnItem, ReturnReceipt


class ReturnService:
    """Track cumulative returns and reject over-returns before mutating inventory."""

    def __init__(self) -> None:
        self._returned: dict[tuple[str, str], int] = {}

    def process(
        self,
        order: Order,
        inventory: Inventory,
        quantities: dict[str, int],
        *,
        loyalty_tier: str = "standard",
    ) -> ReturnReceipt:
        if not quantities:
            raise ValueError("at least one return quantity is required")

        order_items = {item.product.sku: item for item in order.items}
        normalized: dict[str, int] = {}
        for sku, quantity in quantities.items():
            if sku not in order_items:
                raise ValueError(f"sku {sku} is not part of order {order.order_id}")
            if quantity <= 0:
                raise ValueError("return quantity must be positive")
            already_returned = self._returned.get((order.order_id, sku), 0)
            if already_returned + quantity > order_items[sku].quantity:
                raise ValueError(f"return quantity exceeds purchased quantity for {sku}")
            normalized[sku] = quantity

        receipt_items: list[ReturnItem] = []
        subtotal_refund = 0.0
        for sku, quantity in sorted(normalized.items()):
            line = order_items[sku]
            gross = round(line.product.price * quantity, 2)
            discount_share = 0.0 if order.subtotal == 0 else round(order.discount * gross / order.subtotal, 2)
            net = round(gross - discount_share, 2)
            subtotal_refund = round(subtotal_refund + net, 2)
            receipt_items.append(ReturnItem(sku=sku, quantity=quantity, net_refund=net))

        tax_refund = round(subtotal_refund * order.tax_rate, 2)
        total_refund = round(subtotal_refund + tax_refund, 2)
        points_reversed = points_to_reverse(total_refund, loyalty_tier)

        # All validation and calculations precede mutation, preserving all-or-nothing behavior.
        for sku, quantity in normalized.items():
            inventory.restock(sku, quantity)
            key = (order.order_id, sku)
            self._returned[key] = self._returned.get(key, 0) + quantity

        return ReturnReceipt(
            order_id=order.order_id,
            items=tuple(receipt_items),
            subtotal_refund=subtotal_refund,
            tax_refund=tax_refund,
            total_refund=total_refund,
            points_reversed=points_reversed,
        )
