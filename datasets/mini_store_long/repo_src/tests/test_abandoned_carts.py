"""Sweeping abandoned carts recovers stock without overshooting."""

from __future__ import annotations

import pytest
from mini_store.abandoned_carts import sweep
from mini_store.inventory import Inventory


def test_sweeping_recovers_every_abandoned_reservation() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.add_stock("B", 5)
    inv.reserve("A", 3)
    inv.reserve("B", 2)
    assert sweep([("A", 3), ("B", 2)], inv) == 5
    assert (inv.available("A"), inv.available("B")) == (10, 5)


def test_a_sweep_that_overshoots_is_refused_before_it_oversells() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 2)  # abandoned
    inv.reserve("A", 4)  # a live order
    with pytest.raises(ValueError, match="only 6 reserved"):
        sweep([("A", 7)], inv)


def test_available_never_exceeds_stock_on_hand_after_a_sweep() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 4)
    sweep([("A", 4)], inv)
    assert inv.available("A") <= inv.on_hand("A")
