from mini_store.bundle import bundle_price


def test_large_bundle_gets_ten_percent():
    # A 5-item bundle of $100 comes to $90.
    assert bundle_price(100.0, 5) == 90.0
