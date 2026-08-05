from mini_store.discounts import bulk_discount


def test_boundary_uses_the_actual_subtotal():
    assert bulk_discount(500.0, 10) == 50.0


def test_boundary_generalizes_to_a_fractional_subtotal():
    assert bulk_discount(79.95, 10) == 8.0


def test_above_boundary_still_uses_the_actual_subtotal():
    assert bulk_discount(250.0, 11) == 25.0
