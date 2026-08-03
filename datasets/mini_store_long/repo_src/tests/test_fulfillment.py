from __future__ import annotations

import pytest
from mini_store.fulfillment import allocate_shipment
from mini_store.inventory import Inventory


def test_shipment_allocation_cannot_oversubscribe_duplicate_lines():
    inventory = Inventory()
    inventory.add_stock("A", 4)
    with pytest.raises(ValueError):
        allocate_shipment(inventory, [("A", 2), ("A", 3)])
    assert inventory.reserved("A") == 0
