import pytest
from mini_store.models import CartItem, Product


def test_product_fields():
    p = Product(sku="A1", name="Widget", price=9.99, category="tools")
    assert p.sku == "A1"
    assert p.price == 9.99
    assert p.category == "tools"


def test_cart_item_requires_positive_quantity():
    p = Product(sku="A1", name="Widget", price=1.0)
    assert CartItem(product=p, quantity=2).quantity == 2
    with pytest.raises(ValueError):
        CartItem(product=p, quantity=0)
