from mini_store.pricing import apply_tax


def test_ten_percent_and_default_rate_remain_consistent():
    assert apply_tax(100.0, 0.10) == 110.0
    assert apply_tax(50.0) == 54.0
