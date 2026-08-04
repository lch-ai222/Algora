"""The harm the visible tests only approach from the side: overselling.

The visible tests assert that bad releases raise. Raising is the mechanism, not the point. What
the mechanism is protecting is an invariant about the shop: units another order has reserved
must not become sellable again. So these tests do not check for exceptions — they check that
after an adversarial sequence, a purchase that ought to fail still fails.

That distinction matters because both guards can be satisfied superficially. Restoring only the
pool check in ``Inventory.release`` leaves a second cancellation of the same order free to
consume a *different* order's units, since that release fits inside the pool. Restoring only
the idempotency guard in ``cancel_order`` leaves every other release path unchecked.
"""

from __future__ import annotations

import pytest

from mini_store.abandoned_carts import sweep
from mini_store.cancellations import cancel_order
from mini_store.holds import HoldRegistry
from mini_store.inventory import Inventory
from mini_store.models import CartItem, Order, Product


def _order(order_id: str, sku: str, quantity: int) -> Order:
    item = CartItem(product=Product(sku=sku, name=sku, price=10.0), quantity=quantity)
    return Order(order_id=order_id, items=[item])


def test_a_repeated_cancellation_cannot_make_another_order_stock_sellable() -> None:
    """The end-to-end harm: A's three units must not become purchasable by anyone else."""
    inv = Inventory()
    inv.add_stock("A", 5)
    inv.reserve("A", 3)  # order A, still live
    inv.reserve("A", 2)  # order B
    order_b = _order("O-B", "A", 2)
    cancel_order(order_b, inv)

    with pytest.raises(ValueError):
        cancel_order(order_b, inv)

    assert inv.available("A") == 2
    with pytest.raises(ValueError, match="insufficient stock"):
        inv.reserve("A", 3)


def test_an_overshooting_sweep_cannot_make_a_live_order_stock_sellable() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 6)  # live
    inv.reserve("A", 2)  # abandoned

    # Overshooting the whole pool is what this layer can see. A sweep of 4 — more than the 2
    # actually abandoned, but still inside the pool of 8 — is not detectable here, because the
    # pool does not record whose units are whose; that is the caller's responsibility, which is
    # why cancel_order carries its own guard.
    with pytest.raises(ValueError):
        sweep([("A", 9)], inv)

    assert inv.reserved("A") == 8
    with pytest.raises(ValueError, match="insufficient stock"):
        inv.reserve("A", 3)


def test_expiring_a_hold_twice_cannot_free_a_live_reservation() -> None:
    inv = Inventory()
    inv.add_stock("A", 10)
    inv.reserve("A", 5)
    holds = HoldRegistry(inv)
    holds.place("h1", "A", 2)
    holds.expire("h1")

    with pytest.raises(KeyError):
        holds.expire("h1")

    assert inv.reserved("A") == 5


def test_the_reservation_invariant_survives_an_adversarial_sequence() -> None:
    """Whatever is refused along the way, the books must still balance at the end."""
    inv = Inventory()
    inv.add_stock("A", 12)
    inv.reserve("A", 4)
    order = _order("O-1", "A", 3)
    inv.reserve("A", 3)

    for action in (
        lambda: inv.release("A", 99),
        lambda: inv.release("A", 0),
        lambda: inv.release("A", -2),
        lambda: sweep([("A", 20)], inv),
    ):
        with pytest.raises(ValueError):
            action()

    cancel_order(order, inv)
    with pytest.raises(ValueError):
        cancel_order(order, inv)

    assert inv.reserved("A") == 4
    assert inv.available("A") == inv.on_hand("A") - inv.reserved("A")
    assert 0 <= inv.reserved("A") <= inv.on_hand("A")
