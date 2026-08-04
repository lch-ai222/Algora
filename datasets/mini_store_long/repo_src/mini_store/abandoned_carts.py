"""Sweep reservations belonging to carts nobody came back to."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.inventory import Inventory


def sweep(reservations: Iterable[tuple[str, int]], inventory: Inventory) -> int:
    """Release each abandoned reservation, returning the units recovered."""
    recovered = 0
    for sku, quantity in reservations:
        inventory.release(sku, quantity)
        recovered += quantity
    return recovered
