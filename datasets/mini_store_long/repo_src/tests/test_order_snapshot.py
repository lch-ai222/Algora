"""A placed order is a record of what was bought, and records do not move.

An Order stores the cart lines it was priced from. If those lines are the cart's own objects,
then every later cart edit silently rewrites an order that was already placed and paid for —
and the order's stored subtotal stops matching the items it claims to contain.
"""

from __future__ import annotations

from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.orders import place_order
from mini_store.models import Product

WIDGET = Product(sku="W-1", name="Widget", price=10.0)
GADGET = Product(sku="G-1", name="Gadget", price=5.0)


def _placed(cart: Cart):
    inventory = Inventory()
    inventory.add_stock("W-1", 100)
    inventory.add_stock("G-1", 100)
    return place_order("O-1", cart, inventory)


def test_adding_to_the_cart_does_not_change_a_placed_order() -> None:
    cart = Cart()
    cart.add_item(WIDGET, 2)
    order = _placed(cart)

    cart.add_item(WIDGET, 3)

    assert [(i.product.sku, i.quantity) for i in order.items] == [("W-1", 2)]


def test_a_placed_order_stored_total_still_matches_its_own_lines() -> None:
    cart = Cart()
    cart.add_item(WIDGET, 2)
    cart.add_item(GADGET, 1)
    order = _placed(cart)
    recorded_subtotal = order.subtotal

    cart.add_item(WIDGET, 10)

    relined = round(sum(i.product.price * i.quantity for i in order.items), 2)
    assert relined == recorded_subtotal


def test_removing_from_the_cart_does_not_empty_a_placed_order() -> None:
    cart = Cart()
    cart.add_item(WIDGET, 2)
    order = _placed(cart)

    cart.remove_item("W-1")

    assert len(order.items) == 1
    assert order.items[0].quantity == 2
