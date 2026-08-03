import pytest
from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.orders import place_order

_P = Product(sku="A1", name="Widget", price=10.0)


def _setup(stock=10, qty=2):
    inv = Inventory()
    inv.add_stock("A1", stock)
    cart = Cart()
    cart.add_item(_P, qty)
    return cart, inv


def test_place_order_prices_and_reserves():
    cart, inv = _setup(stock=10, qty=2)
    order = place_order("O1", cart, inv)
    assert order.subtotal == 20.0
    assert order.tax == pytest.approx(1.6)
    assert order.total == pytest.approx(21.6)
    assert inv.reserved("A1") == 2


def test_place_order_insufficient_stock_raises():
    cart, inv = _setup(stock=1, qty=2)
    with pytest.raises(ValueError):
        place_order("O2", cart, inv)
