from __future__ import annotations

import inspect

import pytest
from mini_store import (
    checkout,
    fees,
    gift_cards,
    invoices,
    marketplace,
    orders,
    payments,
    promotions,
    quotes,
    shipping,
    subscriptions,
)
from mini_store.pricing import apply_tax, tax_amount, taxed_total


def test_keyword_only_contract_and_compatibility_wrapper():
    assert list(inspect.signature(taxed_total).parameters) == ["amount", "tax_rate"]
    assert inspect.signature(taxed_total).parameters["tax_rate"].kind is inspect.Parameter.KEYWORD_ONLY
    assert tax_amount(19.99, tax_rate=0.0725) == 1.45
    assert taxed_total(19.99, tax_rate=0.0725) == 21.44
    assert apply_tax(19.99, 0.0725) == 21.44
    with pytest.raises(ValueError):
        tax_amount(-0.01, tax_rate=0.08)


def test_no_production_module_calls_legacy_apply_tax():
    for module in (
        checkout,
        fees,
        gift_cards,
        invoices,
        marketplace,
        orders,
        payments,
        promotions,
        quotes,
        shipping,
        subscriptions,
    ):
        assert "apply_tax(" not in inspect.getsource(module)
