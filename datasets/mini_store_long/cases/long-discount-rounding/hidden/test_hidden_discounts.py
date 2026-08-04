"""Hidden checks for the discount primitive.

Two independent aspects were lost together. Restoring only the rounding makes every visible
test pass while an out-of-range percentage still sails through, so these pin the guard as well
as the arithmetic — and pin the fix to the primitive rather than to each caller in turn.
"""

import pytest

from mini_store.clearance import clearance_price
from mini_store.coupons import Coupon, redeem
from mini_store.discounts import percent_off
from mini_store.membership import member_discount


def test_an_out_of_range_percentage_is_rejected():
    with pytest.raises(ValueError):
        percent_off(100.0, 150.0)
    with pytest.raises(ValueError):
        percent_off(100.0, -1.0)


def test_the_guard_reaches_every_caller_of_the_primitive():
    with pytest.raises(ValueError):
        redeem(Coupon(code="TOOMUCH", pct=250.0), 100.0)


def test_discount_values_are_cents_everywhere():
    # Values chosen so an unrounded float differs from the correct one in the third decimal.
    assert percent_off(19.99, 15.0) == 3.0
    assert member_discount(89.99, "premier") == 11.25
    assert clearance_price(12.34) == 8.02


def test_a_zero_percent_discount_is_still_zero():
    assert percent_off(123.45, 0.0) == 0.0
