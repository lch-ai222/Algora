"""Product catalog and search.

``search`` is a spec task: the signature and docstring define the contract, the body is a
stub. Everything else here (add/get/by_category) works and is covered by regression tests.
"""

from __future__ import annotations

from mini_store.models import Product


class Catalog:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def add(self, product: Product) -> None:
        self._products[product.sku] = product

    def get(self, sku: str) -> Product | None:
        return self._products.get(sku)

    def by_category(self, category: str) -> list[Product]:
        return [p for p in self._products.values() if p.category == category]

    def all(self) -> list[Product]:
        return list(self._products.values())

    def search(self, query: str) -> list[Product]:
        """Return products whose name contains ``query`` (case-insensitive), sorted by
        ascending price, then by name for ties. An empty query returns no results.
        """
        raise NotImplementedError("search is not implemented yet")
