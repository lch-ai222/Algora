from mini_store.catalog import Catalog
from mini_store.models import Product


def _catalog():
    c = Catalog()
    c.add(Product(sku="A1", name="Red Widget", price=9.0))
    c.add(Product(sku="B2", name="Blue Widget", price=5.0))
    c.add(Product(sku="C3", name="Green widget", price=5.0))  # tie on price with B2
    c.add(Product(sku="D4", name="Gadget", price=7.0))
    return c


def test_case_insensitive_and_price_then_name_sort():
    c = _catalog()
    results = c.search("WIDGET")
    # price 5.0: "Blue Widget" < "Green widget" by name; then 9.0 "Red Widget"
    assert [p.sku for p in results] == ["B2", "C3", "A1"]


def test_no_match_returns_empty():
    assert _catalog().search("zzz") == []


def test_empty_query_returns_empty():
    assert _catalog().search("") == []
