from mini_store.pricing import apply_tax


def test_custom_rate_and_currency_rounding():
    assert apply_tax(19.99, 0.075) == 21.49


def test_zero_rate_is_identity():
    assert apply_tax(123.45, 0.0) == 123.45
