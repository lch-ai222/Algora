from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from mini_store.inventory import Inventory
from mini_store.loyalty import points_to_reverse
from mini_store.models import Order, ReturnItem, ReturnReceipt


def test_return_domain_contracts_are_explicit_and_typed():
    item = ReturnItem(sku="A", quantity=1, net_refund=10.0)
    receipt = ReturnReceipt(
        order_id="O-1",
        items=(item,),
        subtotal_refund=10.0,
        tax_refund=0.8,
        total_refund=10.8,
        points_reversed=10,
    )
    assert receipt.items == (item,)
    with pytest.raises(FrozenInstanceError):
        item.quantity = 2  # type: ignore[misc]
    assert Order(order_id="O-1").tax_rate == 0.08
    assert points_to_reverse(20.0, "silver") == 20
    assert points_to_reverse(120.0, "gold") == 290

    inventory = Inventory()
    inventory.add_stock("A", 1)
    inventory.restock("A", 2)
    assert inventory.on_hand("A") == 3
    with pytest.raises(ValueError, match="positive"):
        inventory.restock("A", 0)
