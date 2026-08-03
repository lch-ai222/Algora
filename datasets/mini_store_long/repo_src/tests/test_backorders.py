from __future__ import annotations

import pytest
from mini_store.backorders import reserve_backorder
from mini_store.inventory import Inventory


def test_rejected_backorder_with_repeated_sku_is_atomic():
    inventory = Inventory()
    inventory.add_stock("A", 6)
    with pytest.raises(ValueError):
        reserve_backorder(inventory, [("A", 4), ("A", 3)])
    assert inventory.available("A") == 6
