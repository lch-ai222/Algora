from mini_store.loyalty import points_earned


def test_large_gold_order_earns_bonus():
    # A $150 gold order earns 2x points plus a 50-point bonus.
    assert points_earned(150.0, "gold") == 350
