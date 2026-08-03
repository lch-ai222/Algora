from __future__ import annotations

import pytest
from mini_store.inventory import Inventory


def test_order_style_batch_validation_counts_repeated_sku_requirements():
    inventory = Inventory()
    inventory.add_stock("SKU", 7)
    with pytest.raises(ValueError):
        inventory.reserve_many([("SKU", 4), ("SKU", 4)])
    assert inventory.available("SKU") == 7
