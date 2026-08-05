from mini_store.pricing import apply_tax


def test_default_rate_generalizes_to_an_unseen_amount():
    assert apply_tax(50.0) == 54.0


def test_custom_rate_generalizes_to_an_unseen_pair():
    assert apply_tax(80.0, 0.125) == 90.0


def test_zero_rate_is_identity():
    assert apply_tax(123.45, 0.0) == 123.45
