from mini_store.cart import Cart
from mini_store.models import Product


def test_repeated_and_distinct_products_keep_correct_lines():
    cart = Cart()
    widget = Product(sku="A1", name="Widget", price=4.0)
    gadget = Product(sku="B2", name="Gadget", price=6.0)
    cart.add_item(widget, 1)
    cart.add_item(widget, 2)
    cart.add_item(widget, 4)
    cart.add_item(gadget, 1)
    assert len(cart.items()) == 2
    assert cart.item_count() == 8
    assert cart.subtotal() == 34.0
