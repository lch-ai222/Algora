from mini_store.cart import Cart
from mini_store.models import Product


def test_merged_line_can_still_be_removed_as_one_item():
    cart = Cart()
    product = Product(sku="A1", name="Widget", price=4.0)
    cart.add_item(product, 2)
    cart.add_item(product, 3)
    assert len(cart.items()) == 1
    assert cart.item_count() == 5
    cart.remove_item("A1")
    assert cart.item_count() == 0
