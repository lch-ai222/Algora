"""The release side of the reservation invariant.

``reserve`` has always validated. ``release`` is the other half: reserved units are pooled per
SKU, so a caller releasing more than it holds does not merely fail to balance its own books —
it hands somebody else's units back to the sellable pool, and nothing downstream can tell.
"""

from __future__ import annotations

import pytest
from mini_store.inventory import Inventory


def test_releasing_more_than_is_reserved_is_refused() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 3)
    with pytest.raises(ValueError, match="only 3 reserved"):
        inv.release("A", 4)
    assert inv.reserved("A") == 3


def test_releasing_against_no_reservation_is_refused() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    with pytest.raises(ValueError, match="only 0 reserved"):
        inv.release("A", 1)


def test_release_rejects_non_positive_quantities() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 2)
    for quantity in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            inv.release("A", quantity)
    assert inv.reserved("A") == 2


def test_a_refused_release_leaves_the_pool_untouched() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 5)
    with pytest.raises(ValueError):
        inv.release("A", 99)
    assert (inv.reserved("A"), inv.available("A")) == (5, 5)
