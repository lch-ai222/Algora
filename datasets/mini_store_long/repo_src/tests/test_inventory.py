import pytest
from mini_store.inventory import Inventory


def test_add_stock_accumulates():
    inv = Inventory()
    inv.add_stock("A1", 5)
    inv.add_stock("A1", 3)
    assert inv.on_hand("A1") == 8


def test_available_subtracts_reserved():
    inv = Inventory()
    inv.add_stock("A1", 10)
    inv.reserve("A1", 4)
    assert inv.available("A1") == 6


def test_reserve_beyond_available_raises():
    inv = Inventory()
    inv.add_stock("A1", 3)
    with pytest.raises(ValueError):
        inv.reserve("A1", 5)
