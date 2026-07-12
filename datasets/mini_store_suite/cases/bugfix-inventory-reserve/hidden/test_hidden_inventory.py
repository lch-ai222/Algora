import pytest

from mini_store.inventory import Inventory


def test_available_after_multiple_reserves():
    inv = Inventory()
    inv.add_stock("A1", 10)
    inv.reserve("A1", 3)
    inv.reserve("A1", 2)
    assert inv.available("A1") == 5
    assert inv.reserved("A1") == 5


def test_cannot_over_reserve_once_reserved():
    inv = Inventory()
    inv.add_stock("A1", 5)
    inv.reserve("A1", 5)
    assert inv.available("A1") == 0
    with pytest.raises(ValueError):
        inv.reserve("A1", 1)


def test_release_restores_availability():
    inv = Inventory()
    inv.add_stock("A1", 4)
    inv.reserve("A1", 4)
    inv.release("A1", 2)
    assert inv.available("A1") == 2
