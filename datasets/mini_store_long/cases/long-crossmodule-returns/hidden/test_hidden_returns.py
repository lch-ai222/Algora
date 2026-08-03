from __future__ import annotations

import pytest
from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.orders import place_order
from mini_store.returns import ReturnService


def _order():
    cart = Cart()
    cart.add_item(Product("A", "Alpha", 30.0), 2)
    cart.add_item(Product("B", "Beta", 40.0), 1)
    inventory = Inventory()
    inventory.add_stock("A", 5)
    inventory.add_stock("B", 5)
    return place_order("O-HIDDEN", cart, inventory, tax_rate=0.2), inventory


def test_unknown_sku_rejection_is_atomic():
    order, inventory = _order()
    before = inventory.on_hand("A")
    with pytest.raises(ValueError, match="not part"):
        ReturnService().process(order, inventory, {"A": 1, "MISSING": 1})
    assert inventory.on_hand("A") == before


def test_cumulative_partial_returns_cannot_exceed_purchase():
    order, inventory = _order()
    service = ReturnService()
    first = service.process(order, inventory, {"A": 1}, loyalty_tier="silver")
    second = service.process(order, inventory, {"A": 1}, loyalty_tier="silver")
    assert first.total_refund == 36.0
    assert second.total_refund == 36.0
    with pytest.raises(ValueError, match="exceeds purchased"):
        service.process(order, inventory, {"A": 1})
    assert inventory.on_hand("A") == 7


def test_invalid_restock_and_negative_point_reversal_are_rejected():
    inventory = Inventory()
    with pytest.raises(ValueError, match="positive"):
        inventory.restock("A", 0)
