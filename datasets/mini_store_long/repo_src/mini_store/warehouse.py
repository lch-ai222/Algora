"""Warehouse pick-list allocation."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.inventory import Inventory


def allocate_pick_list(inventory: Inventory, lines: Iterable[tuple[str, int]]) -> None:
    inventory.reserve_many(lines)
