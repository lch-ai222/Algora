from mini_store.flash_sale import flash_price


def test_flash_price_lands_on_cents():
    # 22% of 47.85 is 10.527, so the flash price is 47.85 - 10.53.
    assert flash_price(47.85, 22.0) == 37.32


def test_flash_price_stacks_on_a_clearance_price():
    from mini_store.clearance import clearance_price

    assert flash_price(clearance_price(59.99), 10.0) == 35.09
