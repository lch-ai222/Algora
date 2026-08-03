from __future__ import annotations

import pytest
from mini_store.inventory import Inventory
from mini_store.transfers import reserve_transfer


def test_transfer_reservation_is_atomic_across_duplicate_lines():
    inventory = Inventory()
    inventory.add_stock("A", 5)
    inventory.add_stock("B", 1)
    with pytest.raises(ValueError):
        reserve_transfer(inventory, [("A", 2), ("B", 1), ("A", 4)])
    assert inventory.reserved("A") == 0
    assert inventory.reserved("B") == 0
