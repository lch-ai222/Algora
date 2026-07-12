"""Rental refund math.

A full refund (nothing used) carries a $2 processing fee; partial refunds do not. The
processing fee is conditional — applying it to every refund is a classic incomplete fix that
passes the full-refund test but breaks partial refunds.
"""

from __future__ import annotations

PROCESSING_FEE = 2.0


def refund_amount(price: float, days_used: int, rental_days: int) -> float:
    if rental_days <= 0:
        raise ValueError("rental_days must be positive")
    unused = max(0, rental_days - days_used)
    # BUG(refund-fee): full refunds are missing the processing fee entirely.
    return round(price * unused / rental_days, 2)
