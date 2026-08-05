import pytest
from mini_store.cart import Cart
from mini_store.models import Product


def test_quantity_validation_survives_later_merge_changes():
    cart = Cart()
    product = Product(sku="A1", name="Widget", price=4.0)
    with pytest.raises(ValueError):
        cart.add_item(product, 0)
    cart.add_item(product, 2)
    with pytest.raises(ValueError):
        cart.add_item(product, -1)
    assert cart.item_count() == 2
