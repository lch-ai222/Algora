"""Bundle discount tier invariants, kept away from the bundle module's own test file."""

from mini_store.bundle import bundle_price


def test_mid_bundle_stays_five_percent():
    assert bundle_price(100.0, 3) == 95.0


def test_small_bundle_has_no_discount():
    assert bundle_price(100.0, 2) == 100.0
