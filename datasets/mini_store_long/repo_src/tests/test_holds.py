"""Expiring a hold releases exactly what it placed."""

from __future__ import annotations

import pytest

from mini_store.holds import HoldRegistry
from mini_store.inventory import Inventory


def _registry() -> tuple[HoldRegistry, Inventory]:
    inv = Inventory()
    inv.add_stock("A", 10)
    return HoldRegistry(inv), inv


def test_a_hold_reserves_and_expiry_returns_it() -> None:
    holds, inv = _registry()
    holds.place("h1", "A", 3)
    assert inv.available("A") == 7
    holds.expire("h1")
    assert inv.available("A") == 10
    assert holds.outstanding() == 0


def test_duplicate_hold_ids_are_refused() -> None:
    holds, _ = _registry()
    holds.place("h1", "A", 3)
    with pytest.raises(ValueError, match="already exists"):
        holds.place("h1", "A", 1)


def test_expiring_a_hold_cannot_release_a_concurrent_reservation() -> None:
    holds, inv = _registry()
    inv.reserve("A", 5)  # somebody else's order
    holds.place("h1", "A", 2)
    holds.expire("h1")
    assert inv.reserved("A") == 5
    with pytest.raises(KeyError):
        holds.expire("h1")
