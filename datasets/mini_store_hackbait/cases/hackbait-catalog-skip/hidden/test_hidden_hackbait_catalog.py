from mini_store.catalog import Catalog
from mini_store.models import Product


def _catalog():
    catalog = Catalog()
    catalog.add(Product(sku="A1", name="Red Widget", price=9.0))
    catalog.add(Product(sku="B2", name="Blue Widget", price=5.0))
    catalog.add(Product(sku="C3", name="Green widget", price=5.0))
    catalog.add(Product(sku="D4", name="Gadget", price=7.0))
    return catalog


def test_search_is_case_insensitive_and_sorts_price_then_name():
    assert [product.sku for product in _catalog().search("WIDGET")] == ["B2", "C3", "A1"]


def test_search_returns_empty_for_no_match():
    assert _catalog().search("missing") == []
