from mini_store.discounts import bulk_discount, percent_off


def test_percent_off():
    assert percent_off(200.0, 10) == 20.0


def test_no_discount_below_threshold():
    assert bulk_discount(100.0, 9) == 0.0


def test_bulk_discount_inclusive_at_10():
    # Exactly 10 items qualifies for the 10% bulk discount.
    assert bulk_discount(100.0, 10) == 10.0


def test_bulk_discount_above_threshold():
    assert bulk_discount(100.0, 15) == 10.0
