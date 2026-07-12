import pytest

from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.orders import place_order

_P = Product(sku="A1", name="Widget", price=10.0)
_Q = Product(sku="B2", name="Gadget", price=5.0)


def test_bulk_discount_and_tax_applied():
    inv = Inventory()
    inv.add_stock("A1", 20)
    cart = Cart()
    cart.add_item(_P, 10)  # 10 items -> bulk discount
    order = place_order("O1", cart, inv)
    assert order.subtotal == 100.0
    assert order.discount == 10.0
    # discounted 90 -> +8% tax = 97.2
    assert order.total == pytest.approx(97.2)
    assert order.tax == pytest.approx(7.2)


def test_all_or_nothing_reservation():
    inv = Inventory()
    inv.add_stock("A1", 10)
    inv.add_stock("B2", 1)
    cart = Cart()
    cart.add_item(_P, 2)
    cart.add_item(_Q, 5)  # not enough B2
    with pytest.raises(ValueError):
        place_order("O2", cart, inv)
    # nothing should have been reserved
    assert inv.reserved("A1") == 0
    assert inv.reserved("B2") == 0
