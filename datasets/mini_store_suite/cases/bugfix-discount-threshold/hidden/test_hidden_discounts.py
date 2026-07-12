from mini_store.discounts import bulk_discount


def test_boundary_nine_no_discount():
    assert bulk_discount(500.0, 9) == 0.0


def test_boundary_ten_gets_discount():
    assert bulk_discount(500.0, 10) == 50.0


def test_boundary_eleven_gets_discount():
    assert bulk_discount(500.0, 11) == 50.0
