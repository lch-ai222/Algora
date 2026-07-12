from mini_store.cart import Cart
from mini_store.models import Product

_P = Product(sku="A1", name="Widget", price=4.0)
_Q = Product(sku="B2", name="Gadget", price=6.0)


def test_three_adds_same_product_merge():
    c = Cart()
    c.add_item(_P, 1)
    c.add_item(_P, 2)
    c.add_item(_P, 4)
    assert len(c.items()) == 1
    assert c.item_count() == 7


def test_distinct_products_stay_separate():
    c = Cart()
    c.add_item(_P, 1)
    c.add_item(_Q, 1)
    assert len(c.items()) == 2
    assert c.subtotal() == 10.0
