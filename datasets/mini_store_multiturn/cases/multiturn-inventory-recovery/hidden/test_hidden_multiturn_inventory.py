import pytest
from mini_store.inventory import Inventory


def test_reservations_cannot_resell_committed_stock():
    inventory = Inventory()
    inventory.add_stock("A1", 5)
    inventory.reserve("A1", 5)
    assert inventory.available("A1") == 0
    with pytest.raises(ValueError):
        inventory.reserve("A1", 1)
