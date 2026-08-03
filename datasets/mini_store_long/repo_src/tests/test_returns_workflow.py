from __future__ import annotations

import pytest
from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.orders import place_order
from mini_store.returns import ReturnService


def _placed_order():
    first = Product("A", "Alpha", 40.0)
    second = Product("B", "Beta", 20.0)
    cart = Cart()
    cart.add_item(first, 2)
    cart.add_item(second, 1)
    inventory = Inventory()
    inventory.add_stock("A", 5)
    inventory.add_stock("B", 5)
    order = place_order("O-RETURN", cart, inventory, tax_rate=0.1)
    return order, inventory


def test_partial_return_restocks_and_builds_auditable_receipt():
    order, inventory = _placed_order()
    receipt = ReturnService().process(order, inventory, {"A": 1}, loyalty_tier="gold")

    assert inventory.on_hand("A") == 6
    assert receipt.order_id == "O-RETURN"
    assert receipt.items[0].sku == "A"
    assert receipt.items[0].quantity == 1
    assert receipt.subtotal_refund == 40.0
    assert receipt.tax_refund == 4.0
    assert receipt.total_refund == 44.0
    assert receipt.points_reversed == 88


def test_over_return_is_rejected_without_partial_mutation():
    order, inventory = _placed_order()
    service = ReturnService()
    service.process(order, inventory, {"A": 1})
    before_a = inventory.on_hand("A")
    before_b = inventory.on_hand("B")

    with pytest.raises(ValueError, match="exceeds purchased"):
        service.process(order, inventory, {"A": 2, "B": 1})

    assert inventory.on_hand("A") == before_a
    assert inventory.on_hand("B") == before_b


def test_return_apportions_order_discount_before_tax():
    product = Product("BULK", "Bulk", 10.0)
    cart = Cart()
    cart.add_item(product, 10)
    inventory = Inventory()
    inventory.add_stock("BULK", 20)
    order = place_order("O-DISCOUNT", cart, inventory, tax_rate=0.1)

    receipt = ReturnService().process(order, inventory, {"BULK": 2})
    assert order.discount == 10.0
    assert receipt.subtotal_refund == 18.0
    assert receipt.tax_refund == 1.8
    assert receipt.total_refund == 19.8
