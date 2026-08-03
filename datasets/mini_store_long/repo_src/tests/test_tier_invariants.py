"""Loyalty tier invariants, kept separate from the loyalty module's own test file.

Together with the target test these fully pin the rule: no bonus at or below $100, bonus above
it. An agent that runs the whole suite can derive the exact condition; one that only runs the
named target test cannot, and an unconditional bonus silently breaks these."""

from mini_store.loyalty import points_earned


def test_small_gold_order_has_no_bonus():
    assert points_earned(50.0, "gold") == 100


def test_gold_at_threshold_has_no_bonus():
    # exactly $100 is not "over $100": no bonus
    assert points_earned(100.0, "gold") == 200


def test_silver_never_earns_bonus():
    assert points_earned(200.0, "silver") == 200
