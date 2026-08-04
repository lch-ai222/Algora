from mini_store.clearance import clearance_price


def test_clearance_lands_on_cents():
    # 35% of 12.34 is 4.319, so the marked-down price is 12.34 - 4.32.
    assert clearance_price(12.34) == 8.02


def test_clearance_on_a_round_price():
    assert clearance_price(100.0) == 65.0
