from mini_store.pricing import apply_tax


def test_apply_tax_default_on_50():
    assert apply_tax(50.0) == 54.0


def test_apply_tax_zero_rate_is_identity():
    assert apply_tax(123.45, 0.0) == 123.45


def test_apply_tax_ten_percent():
    assert apply_tax(100.0, 0.10) == 110.0
