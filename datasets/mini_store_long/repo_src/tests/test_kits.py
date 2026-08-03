from __future__ import annotations

import pytest
from mini_store.inventory import Inventory
from mini_store.kits import reserve_kit_components


def test_kit_components_aggregate_duplicate_requirements():
    inventory = Inventory()
    inventory.add_stock("SCREW", 10)
    with pytest.raises(ValueError):
        reserve_kit_components(inventory, [("SCREW", 6), ("SCREW", 5)])
    assert inventory.reserved("SCREW") == 0
