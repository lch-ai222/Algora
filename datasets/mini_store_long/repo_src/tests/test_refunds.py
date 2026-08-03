from mini_store.refunds import refund_amount


def test_processing_fee_applied():
    # A refund with nothing used comes back $2 lighter than the price.
    assert refund_amount(100.0, 0, 10) == 98.0
