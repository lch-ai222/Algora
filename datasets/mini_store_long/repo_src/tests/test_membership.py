from mini_store.membership import member_discount


def test_premier_tier_rounds_to_cents():
    # 12.5% of 89.99 is 11.24875.
    assert member_discount(89.99, "premier") == 11.25


def test_plus_tier():
    assert member_discount(240.0, "plus") == 12.0


def test_basic_and_unknown_tiers_earn_nothing():
    assert member_discount(240.0, "basic") == 0.0
    assert member_discount(240.0, "nonexistent") == 0.0
