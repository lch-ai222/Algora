"""Shipment allocation built on Inventory.reserve_many."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.inventory import Inventory


def allocate_shipment(inventory: Inventory, lines: Iterable[tuple[str, int]]) -> None:
    inventory.reserve_many(lines)
