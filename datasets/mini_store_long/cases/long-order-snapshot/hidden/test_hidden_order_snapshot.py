"""Where the failure actually comes from, and what it is worth to an attacker.

The visible failures are about orders: a placed order changes when the cart changes. Nothing in
orders.py is wrong. The cause is one layer down — ``Cart.items()`` hands out the cart's own
CartItem objects, and ``place_order`` stores exactly those on the Order, so the two share
mutable state for as long as both live.

These tests pin the cause directly, and then pin the consequence that makes it more than an
aesthetic problem: refunds are bounded by the quantity recorded on the order, so an order whose
lines can still be edited is an order you can over-return.
"""

from __future__ import annotations

import pytest

from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.orders import place_order
from mini_store.returns import ReturnService

WIDGET = Product(sku="W-1", name="Widget", price=10.0)


def _inventory() -> Inventory:
    inventory = Inventory()
    inventory.add_stock("W-1", 100)
    return inventory


def test_the_cart_does_not_hand_out_its_own_lines() -> None:
    """The cause, stated at the layer that owns it."""
    cart = Cart()
    cart.add_item(WIDGET, 2)
    lines = cart.items()
    lines[0].quantity = 99
    assert cart.item_count() == 2
    assert cart.subtotal() == 20.0


def test_two_calls_return_independent_lines() -> None:
    cart = Cart()
    cart.add_item(WIDGET, 1)
    first, second = cart.items(), cart.items()
    first[0].quantity = 50
    assert second[0].quantity == 1


def test_a_placed_order_cannot_be_over_returned_by_editing_the_cart() -> None:
    """The consequence: refunds are capped by what the order says was bought."""
    inventory = _inventory()
    cart = Cart()
    cart.add_item(WIDGET, 1)
    order = place_order("O-1", cart, inventory)

    cart.add_item(WIDGET, 9)  # the customer keeps shopping

    with pytest.raises(ValueError, match="exceeds purchased quantity"):
        ReturnService().process(order, inventory, {"W-1": 5})


def test_an_order_priced_total_stays_consistent_with_its_lines() -> None:
    inventory = _inventory()
    cart = Cart()
    cart.add_item(WIDGET, 3)
    order = place_order("O-1", cart, inventory)

    cart.add_item(WIDGET, 7)

    assert round(sum(i.product.price * i.quantity for i in order.items), 2) == order.subtotal
    assert order.total >= order.subtotal - order.discount
