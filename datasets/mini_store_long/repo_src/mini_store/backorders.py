"""Backorder allocation through the shared atomic reservation API."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.inventory import Inventory


def reserve_backorder(inventory: Inventory, lines: Iterable[tuple[str, int]]) -> None:
    inventory.reserve_many(lines)
