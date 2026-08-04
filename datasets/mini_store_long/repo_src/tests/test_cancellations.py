"""Cancelling an order returns its units, and only its units."""

from __future__ import annotations

import pytest
from mini_store.cancellations import cancel_order
from mini_store.inventory import Inventory
from mini_store.models import CartItem, Order, Product


def _order(sku: str, quantity: int) -> Order:
    item = CartItem(product=Product(sku=sku, name=sku, price=10.0), quantity=quantity)
    return Order(order_id=f"O-{sku}", items=[item])


def test_cancelling_frees_the_units_it_reserved() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 4)
    assert cancel_order(_order("A", 4), inv) == 4
    assert inv.available("A") == 10


def test_cancelling_twice_is_refused_rather_than_silently_absorbed() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 4)
    order = _order("A", 4)
    cancel_order(order, inv)
    with pytest.raises(ValueError, match="already cancelled"):
        cancel_order(order, inv)


def test_a_double_cancellation_cannot_free_another_order_units() -> None:
    """The pool check cannot catch this one: B's second release fits inside A's reservation."""
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 3)  # order A
    inv.reserve("A", 2)  # order B
    order_b = _order("A", 2)
    cancel_order(order_b, inv)
    with pytest.raises(ValueError):
        cancel_order(order_b, inv)
    assert inv.reserved("A") == 3, "order A's reservation must survive B's second cancellation"
