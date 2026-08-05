from mini_store.inventory import Inventory


def test_cumulative_reserve_then_partial_release():
    inventory = Inventory()
    inventory.add_stock("A1", 10)
    inventory.reserve("A1", 3)
    inventory.reserve("A1", 2)
    assert inventory.available("A1") == 5
    inventory.release("A1", 2)
    assert inventory.available("A1") == 7
