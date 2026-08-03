from __future__ import annotations

import pytest
from mini_store.inventory import Inventory


def test_duplicate_skus_are_aggregated_before_reservation():
    inventory = Inventory()
    inventory.add_stock("A", 5)
    with pytest.raises(ValueError, match="insufficient stock"):
        inventory.reserve_many([("A", 3), ("A", 3)])
    assert inventory.reserved("A") == 0
    assert inventory.available("A") == 5
