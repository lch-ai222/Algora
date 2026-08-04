"""Per-model cost normalization with explicit provenance.

Cross-agent comparison needs cost per success, and that number is only meaningful if the
rate behind it is attributable. Three rules make it so:

1. **A missing rate is `None`, never `0.0`.** A zero reads as "this was free" in every table
   and chart downstream; the previous flat `LLM_*_COST_PER_1K_USD` settings defaulted to zero,
   so an unpriced run silently reported a cost of nothing. Unknown must stay unknown.
2. **Rates carry a source and a date.** Vendor prices change, so a table entry without
   ``source`` and ``as_of`` is treated as unverified and yields no cost.
3. **No implicit currency conversion.** A CNY-priced model produces a USD figure only when an
   operator has supplied ``usd_per_cny`` in the table. Applying a guessed FX rate would
   manufacture precision that the comparison then inherits.

The table lives in ``config/pricing.json`` so rates are reviewable data, not code, and the
revision used by a run is recorded in its artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

DEFAULT_PRICING_PATH = Path("config/pricing.json")
PRICING_SCHEMA_VERSION = 1

CostSource = Literal["table", "unavailable"]


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    currency: str
    prompt_per_1k: float | None
    completion_per_1k: float | None
    cached_prompt_per_1k: float | None = None
    source: str | None = None
    as_of: str | None = None
    note: str | None = None

    @property
    def usable(self) -> bool:
        """A rate counts only when it is complete and attributable."""
        return (
            self.prompt_per_1k is not None
            and self.completion_per_1k is not None
            and bool(self.source)
            and bool(self.as_of)
        )

    def unusable_reason(self) -> str:
        if self.prompt_per_1k is None or self.completion_per_1k is None:
            return f"no rate recorded for {self.provider}/{self.model}"
        return f"rate for {self.provider}/{self.model} lacks source/as_of provenance"


@dataclass(frozen=True)
class CostEstimate:
    amount_usd: float | None
    source: CostSource
    reason: str | None = None
    #: True when prompt-cache tokens were billed at the full prompt rate because the table
    #: has no cached rate — the figure is then an upper bound, not an estimate.
    upper_bound: bool = False

    @property
    def available(self) -> bool:
        return self.source == "table" and self.amount_usd is not None


UNAVAILABLE = CostEstimate(amount_usd=None, source="unavailable")


@dataclass(frozen=True)
class PriceTable:
    revision: str
    path: str
    usd_per_cny: float | None = None
    prices: tuple[ModelPrice, ...] = ()

    def lookup(self, provider: str, model: str | None) -> ModelPrice | None:
        if not model:
            return None
        for price in self.prices:
            if price.provider == provider and price.model == model:
                return price
        return None

    def provenance(self) -> dict[str, object]:
        """Recorded on every run so a cost figure can be traced back to the rates used."""
        return {
            "pricing_revision": self.revision,
            "pricing_path": self.path,
            "pricing_entries": len(self.prices),
            "pricing_usable_entries": sum(1 for p in self.prices if p.usable),
            "usd_per_cny": self.usd_per_cny,
        }

    def estimate(
        self,
        *,
        provider: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cached_prompt_tokens: int = 0,
    ) -> CostEstimate:
        price = self.lookup(provider, model)
        if price is None:
            return CostEstimate(
                None, "unavailable", f"no pricing entry for {provider}/{model} in {self.path}"
            )
        if not price.usable:
            return CostEstimate(None, "unavailable", f"{price.unusable_reason()} in {self.path}")

        rate_to_usd = self._to_usd_factor(price.currency)
        if rate_to_usd is None:
            return CostEstimate(
                None,
                "unavailable",
                f"{price.currency} rate for {provider}/{model} needs an explicit "
                f"usd_per_cny in {self.path}; no conversion is assumed",
            )

        cached = max(0, min(cached_prompt_tokens, prompt_tokens))
        uncached = max(0, prompt_tokens - cached)
        upper_bound = cached > 0 and price.cached_prompt_per_1k is None
        cached_rate = (
            price.cached_prompt_per_1k if price.cached_prompt_per_1k is not None else price.prompt_per_1k
        )
        native = (
            uncached * price.prompt_per_1k / 1000
            + cached * cached_rate / 1000
            + completion_tokens * price.completion_per_1k / 1000
        )
        return CostEstimate(
            amount_usd=round(native * rate_to_usd, 8),
            source="table",
            reason="prompt-cache tokens billed at the full prompt rate" if upper_bound else None,
            upper_bound=upper_bound,
        )

    def _to_usd_factor(self, currency: str) -> float | None:
        if currency.upper() == "USD":
            return 1.0
        if currency.upper() == "CNY":
            return self.usd_per_cny
        return None


EMPTY_TABLE = PriceTable(revision="none", path="<none>", prices=())


def load_price_table(path: str | Path | None = None) -> PriceTable:
    """Load the table, or return an empty one when it is absent.

    A missing file is not an error: cost simply stays unavailable, which is the correct
    behavior for a run nobody has priced yet.
    """
    resolved = Path(path or DEFAULT_PRICING_PATH)
    if not resolved.is_file():
        return PriceTable(revision="missing", path=str(resolved), prices=())
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if data.get("schema_version") != PRICING_SCHEMA_VERSION:
        raise ValueError(
            f"{resolved}: unsupported pricing schema_version "
            f"{data.get('schema_version')!r} (expected {PRICING_SCHEMA_VERSION})"
        )
    prices = tuple(
        ModelPrice(
            provider=str(entry["provider"]),
            model=str(entry["model"]),
            currency=str(entry.get("currency", "USD")),
            prompt_per_1k=entry.get("prompt_per_1k"),
            completion_per_1k=entry.get("completion_per_1k"),
            cached_prompt_per_1k=entry.get("cached_prompt_per_1k"),
            source=entry.get("source"),
            as_of=entry.get("as_of"),
            note=entry.get("note"),
        )
        for entry in data.get("models", [])
    )
    return PriceTable(
        revision=str(data.get("revision", "unversioned")),
        path=str(resolved),
        usd_per_cny=data.get("usd_per_cny"),
        prices=prices,
    )


@lru_cache(maxsize=8)
def cached_price_table(path: str | None = None) -> PriceTable:
    """Process-local cache; the table is immutable for the duration of a run."""
    return load_price_table(path)
