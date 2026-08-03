from mini_store.models import CartItem, Product
from mini_store.pricing import apply_tax, line_total, subtotal

_P = Product(sku="A1", name="Widget", price=10.0)


def test_line_total():
    assert line_total(CartItem(product=_P, quantity=3)) == 30.0


def test_subtotal():
    items = [CartItem(product=_P, quantity=2), CartItem(product=Product("B2", "Gadget", 5.0), quantity=1)]
    assert subtotal(items) == 25.0


def test_apply_tax_is_percentage():
    # 8% tax on 100 -> 108, not 100.08
    assert apply_tax(100.0) == 108.0


def test_apply_tax_custom_rate():
    assert apply_tax(200.0, 0.05) == 210.0
