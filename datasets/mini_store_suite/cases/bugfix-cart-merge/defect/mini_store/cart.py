"""Shopping cart. Adding the same product twice should merge quantities, not duplicate."""

from __future__ import annotations

from mini_store.models import CartItem, Product
from mini_store.pricing import subtotal


class Cart:
    def __init__(self) -> None:
        self._items: dict[str, CartItem] = {}

    def add_item(self, product: Product, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._items[product.sku] = CartItem(product=product, quantity=quantity)

    def remove_item(self, sku: str) -> None:
        self._items.pop(sku, None)

    def items(self) -> list[CartItem]:
        return list(self._items.values())

    def item_count(self) -> int:
        return sum(i.quantity for i in self._items.values())

    def subtotal(self) -> float:
        return subtotal(self.items())
