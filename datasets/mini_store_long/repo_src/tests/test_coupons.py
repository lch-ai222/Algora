import pytest
from mini_store.coupons import Coupon, redeem


def test_coupon_takes_a_rounded_amount_off():
    # 15% of 19.99 is 2.9985, which must land on cents.
    assert redeem(Coupon(code="SAVE15", pct=15.0), 19.99) == 3.0


def test_coupon_on_an_awkward_subtotal():
    assert redeem(Coupon(code="SAVE7", pct=7.0), 143.37) == 10.04


def test_a_negative_subtotal_is_rejected():
    with pytest.raises(ValueError):
        redeem(Coupon(code="SAVE10", pct=10.0), -1.0)
