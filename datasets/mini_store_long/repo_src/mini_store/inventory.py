"""Stock tracking with reservations.

Invariant: available = on_hand - reserved. Reserved units are committed to pending orders
and must not be sellable again.
"""

from __future__ import annotations

from collections.abc import Iterable


class Inventory:
    def __init__(self) -> None:
        self._on_hand: dict[str, int] = {}
        self._reserved: dict[str, int] = {}

    def add_stock(self, sku: str, quantity: int) -> None:
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        self._on_hand[sku] = self._on_hand.get(sku, 0) + quantity

    def on_hand(self, sku: str) -> int:
        return self._on_hand.get(sku, 0)

    def reserved(self, sku: str) -> int:
        return self._reserved.get(sku, 0)

    def available(self, sku: str) -> int:
        return self._on_hand.get(sku, 0) - self._reserved.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.available(sku) < quantity:
            raise ValueError(f"insufficient stock for {sku}: need {quantity}, have {self.available(sku)}")
        self._reserved[sku] = self._reserved.get(sku, 0) + quantity

    def reserve_many(self, requests: Iterable[tuple[str, int]]) -> None:
        """Atomically reserve a batch, aggregating duplicate SKU entries before validation."""
        totals: dict[str, int] = {}
        for sku, quantity in requests:
            if quantity <= 0:
                raise ValueError("quantity must be positive")
            totals[sku] = totals.get(sku, 0) + quantity

        for sku, quantity in totals.items():
            if self.available(sku) < quantity:
                raise ValueError(f"insufficient stock for {sku}: need {quantity}, have {self.available(sku)}")

        for sku, quantity in totals.items():
            self._reserved[sku] = self._reserved.get(sku, 0) + quantity

    def release(self, sku: str, quantity: int) -> None:
        self._reserved[sku] = max(0, self._reserved.get(sku, 0) - quantity)

    def restock(self, sku: str, quantity: int) -> None:
        """Put returned units back on hand without altering existing reservations."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._on_hand[sku] = self._on_hand.get(sku, 0) + quantity
