from __future__ import annotations

import pytest
from mini_store.inventory import Inventory


def test_failed_batch_never_makes_available_stock_negative():
    inventory = Inventory()
    inventory.add_stock("A", 2)
    with pytest.raises(ValueError):
        inventory.reserve_many([("A", 2), ("A", 1)])
    assert inventory.available("A") == 2


def test_invalid_quantity_does_not_apply_earlier_lines():
    inventory = Inventory()
    inventory.add_stock("A", 5)
    with pytest.raises(ValueError, match="positive"):
        inventory.reserve_many([("A", 2), ("B", 0)])
    assert inventory.reserved("A") == 0
