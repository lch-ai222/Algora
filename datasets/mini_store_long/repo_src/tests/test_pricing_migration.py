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
from mini_store.cart import Cart
from mini_store.inventory import Inventory
from mini_store.models import Product
from mini_store.pricing import tax_amount, taxed_total

CALLSITE_MODULES = (
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


def test_new_pricing_api_is_keyword_only_and_validated():
    assert tax_amount(100.0, tax_rate=0.08) == 8.0
    assert taxed_total(100.0, tax_rate=0.08) == 108.0
    with pytest.raises(TypeError):
        taxed_total(100.0, 0.08)  # type: ignore[misc]
    with pytest.raises(ValueError):
        taxed_total(100.0, tax_rate=8)


def test_all_production_call_sites_use_taxed_total():
    for module in CALLSITE_MODULES:
        source = inspect.getsource(module)
        assert "apply_tax(" not in source, module.__name__
        assert "taxed_total(" in source, module.__name__


def test_migrated_flows_preserve_behavior():
    product = Product("SKU", "Widget", 25.0)
    cart = Cart()
    cart.add_item(product, 2)
    inventory = Inventory()
    inventory.add_stock("SKU", 2)

    order = orders.place_order("O-1", cart, inventory, tax_rate=0.1)
    assert order.total == 55.0
    assert checkout.checkout_total(cart, tax_rate=0.1) == 55.0
    assert invoices.invoice_total(50.0, tax_rate=0.1) == 55.0
    assert quotes.quote_total([20.0, 30.0], tax_rate=0.1) == 55.0
    assert shipping.shipping_total(10.0, tax_rate=0.1) == 11.0
    assert subscriptions.renewal_total(10.0, 5, tax_rate=0.1) == 55.0
    assert fees.service_fee_total(10.0, tax_rate=0.1) == 11.0
    assert gift_cards.gift_card_total(45.0, 5.0, tax_rate=0.1) == 55.0
    assert marketplace.buyer_total(45.0, 5.0, tax_rate=0.1) == 55.0
    assert payments.authorization_total(50.0, tax_rate=0.1) == 55.0
    assert promotions.promotional_total(60.0, 10.0, tax_rate=0.1) == 55.0
