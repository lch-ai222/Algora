"""Short-lived stock holds, released when they expire."""

from __future__ import annotations

from mini_store.inventory import Inventory


class HoldRegistry:
    def __init__(self, inventory: Inventory) -> None:
        self._inventory = inventory
        self._holds: dict[str, tuple[str, int]] = {}

    def place(self, hold_id: str, sku: str, quantity: int) -> None:
        if hold_id in self._holds:
            raise ValueError(f"hold {hold_id} already exists")
        self._inventory.reserve(sku, quantity)
        self._holds[hold_id] = (sku, quantity)

    def expire(self, hold_id: str) -> None:
        sku, quantity = self._holds.pop(hold_id)
        self._inventory.release(sku, quantity)

    def outstanding(self) -> int:
        return sum(quantity for _, quantity in self._holds.values())
