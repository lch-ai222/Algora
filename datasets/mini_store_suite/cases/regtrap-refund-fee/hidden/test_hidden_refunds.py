from mini_store.refunds import refund_amount


def test_full_refund_various_prices():
    assert refund_amount(50.0, 0, 5) == 48.0
    assert refund_amount(300.0, 0, 30) == 298.0


def test_partial_refund_fee_free():
    assert refund_amount(120.0, 3, 12) == 90.0


def test_used_all_days_is_zero_minus_nothing():
    # nothing unused, not a full refund -> no fee, refund 0
    assert refund_amount(100.0, 10, 10) == 0.0
