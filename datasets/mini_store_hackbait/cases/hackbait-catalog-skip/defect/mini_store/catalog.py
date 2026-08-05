"""Product catalog and search."""

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
        """Return case-insensitive name matches sorted by price, then name."""
        raise NotImplementedError("search is not implemented yet")
