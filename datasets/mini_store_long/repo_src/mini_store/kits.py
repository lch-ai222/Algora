"""Reserve component quantities needed to assemble a kit."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.inventory import Inventory


def reserve_kit_components(inventory: Inventory, components: Iterable[tuple[str, int]]) -> None:
    inventory.reserve_many(components)
