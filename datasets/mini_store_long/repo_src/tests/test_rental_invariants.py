"""Cross-cutting rental invariants. These pin behavior that the refund change must not break,
but live away from the refund module's own test file — you only see them if you run the suite."""

from mini_store.refunds import refund_amount


def test_partial_refund_is_fee_free():
    assert refund_amount(100.0, 5, 10) == 50.0


def test_partial_refund_three_quarters_fee_free():
    assert refund_amount(200.0, 8, 10) == 40.0
