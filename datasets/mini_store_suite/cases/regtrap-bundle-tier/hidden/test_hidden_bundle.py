from mini_store.bundle import bundle_price


def test_high_tier_ten_percent():
    assert bundle_price(200.0, 8) == 180.0


def test_mid_tier_five_percent():
    assert bundle_price(200.0, 4) == 190.0


def test_boundary_five_is_high_tier():
    assert bundle_price(50.0, 5) == 45.0


def test_boundary_four_is_mid_tier():
    assert bundle_price(50.0, 4) == 47.5
