"""W1-7: cost normalization must refuse to invent a number.

Cost per success is only comparable across agents if the rate behind it is attributable.
Every test here pins one way that guarantee could quietly break — an unpriced model reading
as free, an unsourced rate being trusted, a currency silently converted, or a partially
priced trial being summed anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeagent_eval.pricing import (
    PRICING_SCHEMA_VERSION,
    ModelPrice,
    PriceTable,
    load_price_table,
)

SHIPPED_TABLE = Path("config/pricing.json")


def table(*prices: ModelPrice, usd_per_cny: float | None = None) -> PriceTable:
    return PriceTable(revision="test", path="test.json", usd_per_cny=usd_per_cny, prices=prices)


def priced(**over) -> ModelPrice:
    defaults = dict(
        provider="deepseek",
        model="deepseek-chat",
        currency="USD",
        prompt_per_1k=0.28,
        completion_per_1k=0.42,
        source="https://vendor.example/pricing",
        as_of="2026-08-01",
    )
    return ModelPrice(**{**defaults, **over})


def estimate(t: PriceTable, **over):
    args = dict(provider="deepseek", model="deepseek-chat", prompt_tokens=1000, completion_tokens=1000)
    return t.estimate(**{**args, **over})


# --------------------------------------------------------------------------- #
# Unknown must stay unknown
# --------------------------------------------------------------------------- #
def test_an_unpriced_model_is_unavailable_not_free():
    """0.0 is indistinguishable from 'this was free' in every table and chart downstream."""
    result = estimate(table(), model="glm-4.6")

    assert result.amount_usd is None
    assert result.source == "unavailable"
    assert result.available is False
    assert "no pricing entry" in result.reason


@pytest.mark.parametrize(
    ("field", "value"),
    [("prompt_per_1k", None), ("completion_per_1k", None), ("source", None), ("as_of", None)],
)
def test_an_incomplete_or_unsourced_rate_yields_no_cost(field, value):
    """Vendor prices change, so a rate nobody can date or trace is not usable evidence."""
    result = estimate(table(priced(**{field: value})))

    assert result.amount_usd is None
    assert result.source == "unavailable"


def test_a_complete_rate_prices_the_call():
    result = estimate(table(priced()))

    assert result.source == "table"
    assert result.available is True
    assert result.amount_usd == pytest.approx(0.28 / 1000 * 1000 + 0.42 / 1000 * 1000, rel=1e-9)
    assert result.upper_bound is False


# --------------------------------------------------------------------------- #
# Currency is never assumed
# --------------------------------------------------------------------------- #
def test_a_foreign_currency_without_a_configured_rate_is_unavailable():
    """Applying a guessed FX rate would manufacture precision the comparison then inherits."""
    result = estimate(table(priced(currency="CNY")))

    assert result.amount_usd is None
    assert "usd_per_cny" in result.reason
    assert "no conversion is assumed" in result.reason


def test_a_foreign_currency_converts_only_with_an_explicit_rate():
    result = estimate(table(priced(currency="CNY", prompt_per_1k=2.0, completion_per_1k=8.0),
                            usd_per_cny=0.14))

    assert result.source == "table"
    assert result.amount_usd == pytest.approx((2.0 + 8.0) * 0.14, rel=1e-9)


def test_an_unhandled_currency_is_unavailable():
    result = estimate(table(priced(currency="EUR"), usd_per_cny=0.14))

    assert result.amount_usd is None


# --------------------------------------------------------------------------- #
# Prompt cache
# --------------------------------------------------------------------------- #
def test_cache_hits_are_billed_at_the_cached_rate():
    result = estimate(
        table(priced(cached_prompt_per_1k=0.028)), prompt_tokens=1000, cached_prompt_tokens=800
    )

    expected = 200 * 0.28 / 1000 + 800 * 0.028 / 1000 + 1000 * 0.42 / 1000
    assert result.amount_usd == pytest.approx(expected, rel=1e-9)
    assert result.upper_bound is False


def test_a_missing_cached_rate_produces_a_flagged_upper_bound():
    """Falling back to the full prompt rate overstates cost, so the figure must say so
    rather than pass as an estimate."""
    result = estimate(table(priced()), prompt_tokens=1000, cached_prompt_tokens=800)

    assert result.upper_bound is True
    assert "full prompt rate" in result.reason
    assert result.amount_usd == pytest.approx(0.28 + 0.42, rel=1e-9)


def test_cached_tokens_are_clamped_to_the_prompt_total():
    """A vendor reporting more cache hits than prompt tokens must not produce a negative bill."""
    result = estimate(
        table(priced(cached_prompt_per_1k=0.0)), prompt_tokens=100, cached_prompt_tokens=9999
    )

    assert result.amount_usd == pytest.approx(1000 * 0.42 / 1000, rel=1e-9)


# --------------------------------------------------------------------------- #
# Loading and provenance
# --------------------------------------------------------------------------- #
def test_a_missing_table_is_not_an_error_just_unpriced():
    loaded = load_price_table(Path("does/not/exist.json"))

    assert loaded.prices == ()
    assert estimate(loaded).source == "unavailable"


def test_an_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps({"schema_version": 999, "models": []}))

    with pytest.raises(ValueError, match="unsupported pricing schema_version"):
        load_price_table(path)


def test_provenance_records_what_backed_the_numbers():
    provenance = table(priced(), priced(model="unpriced", prompt_per_1k=None)).provenance()

    assert provenance["pricing_revision"] == "test"
    assert provenance["pricing_entries"] == 2
    assert provenance["pricing_usable_entries"] == 1


# --------------------------------------------------------------------------- #
# The shipped table
# --------------------------------------------------------------------------- #
def test_the_shipped_table_parses_and_covers_the_model_ladder():
    loaded = load_price_table(SHIPPED_TABLE)
    entries = {(p.provider, p.model) for p in loaded.prices}

    assert json.loads(SHIPPED_TABLE.read_text())["schema_version"] == PRICING_SCHEMA_VERSION
    assert ("deepseek", "deepseek-v4-flash") in entries
    assert ("deepseek", "deepseek-v4-pro") in entries
    # The ladder's three rungs: flagship, mid, free weak tier.
    assert ("zhipu", "glm-5.2") in entries
    assert ("zhipu", "glm-4.5-air") in entries
    assert ("zhipu", "glm-4.7-flash") in entries


def test_every_shipped_rate_carries_its_source_and_date():
    for price in load_price_table(SHIPPED_TABLE).prices:
        assert price.source, f"{price.model} has a rate with no source"
        assert price.as_of, f"{price.model} has a rate with no as_of date"


def test_the_shipped_usd_rates_price_a_call():
    loaded = load_price_table(SHIPPED_TABLE)
    result = loaded.estimate(
        provider="deepseek", model="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=1000
    )

    assert result.available is True
    assert result.amount_usd == pytest.approx(0.00014 + 0.00028, rel=1e-9)


def test_the_shipped_cny_rates_stay_unavailable_without_an_exchange_rate():
    """The table is priced but deliberately carries no usd_per_cny, so GLM cost is withheld
    rather than converted at a guessed rate."""
    loaded = load_price_table(SHIPPED_TABLE)
    result = loaded.estimate(
        provider="zhipu", model="glm-5.2", prompt_tokens=1000, completion_tokens=1000
    )

    assert loaded.usd_per_cny is None
    assert result.amount_usd is None
    assert "usd_per_cny" in result.reason


def test_a_free_model_is_zero_cost_not_unpriced():
    """glm-4.7-flash is genuinely free. That has to be distinguishable from 'we do not know',
    which is the whole reason an unpriced model reports None instead of 0.0."""
    loaded = load_price_table(SHIPPED_TABLE)
    free = loaded.lookup("zhipu", "glm-4.7-flash")

    assert free.usable is True
    assert free.prompt_per_1k == 0.0
    priced = PriceTable(revision="t", path="t", usd_per_cny=0.14, prices=(free,))
    result = priced.estimate(
        provider="zhipu", model="glm-4.7-flash", prompt_tokens=10_000, completion_tokens=10_000
    )
    assert result.available is True
    assert result.amount_usd == 0.0


# --------------------------------------------------------------------------- #
# Aliases and length-tiered rates
# --------------------------------------------------------------------------- #
def test_a_legacy_alias_resolves_to_the_billed_model():
    """Verified live on 2026-08-04: deepseek-chat and deepseek-reasoner both serve
    deepseek-v4-flash, so a lookup miss on the alias would drop cost for a priced run."""
    loaded = load_price_table(SHIPPED_TABLE)

    for name in ("deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"):
        assert loaded.lookup("deepseek", name).model == "deepseek-v4-flash", name
    assert loaded.lookup("deepseek", "deepseek-v4-pro").model == "deepseek-v4-pro"


def test_an_alias_does_not_leak_across_providers():
    loaded = load_price_table(SHIPPED_TABLE)

    assert loaded.lookup("zhipu", "deepseek-chat") is None


def test_a_length_tiered_rate_is_reported_as_an_upper_bound():
    """The entry carries the most expensive tier, so the figure must not pass as an estimate."""
    result = estimate(table(priced(tiered=True)))

    assert result.available is True
    assert result.upper_bound is True
    assert "most expensive tier" in result.reason


def test_tier_and_cache_fallbacks_are_both_reported():
    result = estimate(table(priced(tiered=True)), prompt_tokens=1000, cached_prompt_tokens=500)

    assert result.upper_bound is True
    assert "full prompt rate" in result.reason
    assert "most expensive tier" in result.reason
