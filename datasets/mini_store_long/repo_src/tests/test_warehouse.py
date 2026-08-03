from __future__ import annotations

import pytest
from mini_store.inventory import Inventory
from mini_store.warehouse import allocate_pick_list


def test_pick_list_failure_does_not_commit_earlier_lines():
    inventory = Inventory()
    inventory.add_stock("A", 4)
    inventory.add_stock("B", 1)
    with pytest.raises(ValueError):
        allocate_pick_list(inventory, [("A", 2), ("B", 1), ("A", 3)])
    assert inventory.reserved("A") == 0
    assert inventory.reserved("B") == 0
