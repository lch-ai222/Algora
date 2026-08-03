from mini_store.catalog import Catalog
from mini_store.models import Product


def _catalog():
    c = Catalog()
    c.add(Product(sku="A1", name="Red Widget", price=9.0, category="tools"))
    c.add(Product(sku="B2", name="Blue Widget", price=5.0, category="tools"))
    c.add(Product(sku="C3", name="Gadget", price=7.0, category="gizmos"))
    return c


def test_add_get():
    c = _catalog()
    assert c.get("A1").name == "Red Widget"
    assert c.get("nope") is None


def test_by_category():
    c = _catalog()
    assert {p.sku for p in c.by_category("tools")} == {"A1", "B2"}


def test_search_matches_case_insensitive_sorted_by_price():
    c = _catalog()
    results = c.search("widget")
    assert [p.sku for p in results] == ["B2", "A1"]  # 5.0 before 9.0


def test_search_empty_query_returns_nothing():
    assert _catalog().search("") == []
