from __future__ import annotations

import pytest
from mini_store.inventory import Inventory


def test_generator_input_is_consumed_once_and_duplicates_are_aggregated():
    inventory = Inventory()
    inventory.add_stock("A", 4)
    requests = ((sku, quantity) for sku, quantity in [("A", 2), ("A", 3)])
    with pytest.raises(ValueError):
        inventory.reserve_many(requests)
    assert inventory.reserved("A") == 0


def test_successful_batch_aggregates_and_commits_once():
    inventory = Inventory()
    inventory.add_stock("A", 6)
    inventory.reserve_many([("A", 2), ("A", 3)])
    assert inventory.reserved("A") == 5
    assert inventory.available("A") == 1
