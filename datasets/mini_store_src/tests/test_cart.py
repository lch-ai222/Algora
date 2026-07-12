from mini_store.cart import Cart
from mini_store.models import Product

_P = Product(sku="A1", name="Widget", price=4.0)
_Q = Product(sku="B2", name="Gadget", price=6.0)


def test_single_add():
    c = Cart()
    c.add_item(_P, 2)
    assert c.item_count() == 2
    assert c.subtotal() == 8.0


def test_remove_item():
    c = Cart()
    c.add_item(_P, 2)
    c.remove_item("A1")
    assert c.item_count() == 0


def test_add_same_product_merges():
    c = Cart()
    c.add_item(_P, 2)
    c.add_item(_P, 3)
    assert len(c.items()) == 1
    assert c.item_count() == 5
