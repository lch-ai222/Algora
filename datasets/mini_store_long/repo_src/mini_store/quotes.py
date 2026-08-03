"""Quote calculations."""

from __future__ import annotations

from collections.abc import Iterable

from mini_store.pricing import DEFAULT_TAX_RATE, taxed_total


def quote_total(amounts: Iterable[float], *, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    return taxed_total(round(sum(amounts), 2), tax_rate=tax_rate)
