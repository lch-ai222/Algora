"""Cost coverage, cost-per-success, and paired cost deltas.

Unknown price is not zero. Aggregate cost and cost-per-success are published only when every
valid trial has a usable cost. Paired deltas likewise require a complete paired grid and cost
on both sides; partial subsets are counted but never turned into a headline estimate.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

from codeagent_eval.stats.bootstrap import MIN_USEFUL_CLUSTERS
from codeagent_eval.stats.mcnemar import UnpairedSamples


@dataclass(frozen=True)
class CostObservation:
    key: str
    case_id: str
    task_success: bool
    cost_usd: float | None


@dataclass(frozen=True)
class CostSummary:
    n_trials: int
    n_priced: int
    n_successes: int
    coverage: float
    observed_cost_usd: float
    total_cost_usd: float | None
    cost_per_success_usd: float | None
    available: bool
    reason: str | None


@dataclass(frozen=True)
class PairedCostComparison:
    n_pairs: int
    n_both_priced: int
    both_success_pairs: int
    available: bool
    mean_delta_usd: float | None
    median_delta_usd: float | None
    case_macro_delta_usd: float | None
    case_macro_delta_low_usd: float | None
    case_macro_delta_high_usd: float | None
    both_success_mean_delta_usd: float | None
    n_case_clusters: int
    resamples: int
    confidence: float
    warning: str | None
    reason: str | None


def summarize_costs(observations: list[CostObservation]) -> CostSummary:
    """Summarize one arm without presenting a partial total as the experiment cost."""
    if any(item.cost_usd is not None and item.cost_usd < 0 for item in observations):
        raise ValueError("costs must be non-negative")
    priced = [item for item in observations if item.cost_usd is not None]
    successes = sum(item.task_success for item in observations)
    observed = sum(item.cost_usd for item in priced if item.cost_usd is not None)
    n = len(observations)
    complete = bool(n) and len(priced) == n

    reason = None
    if not n:
        reason = "no valid trials"
    elif not complete:
        reason = f"cost available for {len(priced)}/{n} valid trials"
    elif successes == 0:
        reason = "no successful trials; cost per success is undefined"

    return CostSummary(
        n_trials=n,
        n_priced=len(priced),
        n_successes=successes,
        coverage=len(priced) / n if n else 0.0,
        observed_cost_usd=observed,
        total_cost_usd=observed if complete else None,
        cost_per_success_usd=(observed / successes if complete and successes else None),
        available=complete,
        reason=reason,
    )


def paired_cost_comparison(
    a: dict[str, CostObservation], b: dict[str, CostObservation],
    *, label_a: str = "A", label_b: str = "B",
    n_resamples: int = 10_000, confidence: float = 0.95, seed: int = 0,
) -> PairedCostComparison:
    """Compare costs on the same trial grid, refusing subset-only estimates."""
    if a.keys() != b.keys():
        missing_b = sorted(a.keys() - b.keys())[:3]
        missing_a = sorted(b.keys() - a.keys())[:3]
        raise UnpairedSamples(
            f"{label_a} and {label_b} do not cover the same trials; "
            f"missing from {label_b}: {missing_b}, missing from {label_a}: {missing_a}"
        )
    if not a:
        raise UnpairedSamples("no trials to compare")
    if any(item.cost_usd is not None and item.cost_usd < 0 for item in [*a.values(), *b.values()]):
        raise ValueError("costs must be non-negative")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")

    both_priced = [key for key in a if a[key].cost_usd is not None and b[key].cost_usd is not None]
    both_success = [key for key in both_priced if a[key].task_success and b[key].task_success]
    if len(both_priced) != len(a):
        return PairedCostComparison(
            n_pairs=len(a), n_both_priced=len(both_priced),
            both_success_pairs=len(both_success), available=False,
            mean_delta_usd=None, median_delta_usd=None, case_macro_delta_usd=None,
            case_macro_delta_low_usd=None, case_macro_delta_high_usd=None,
            both_success_mean_delta_usd=None, n_case_clusters=0,
            resamples=n_resamples, confidence=confidence, warning=None,
            reason=f"paired cost available for {len(both_priced)}/{len(a)} trials",
        )

    deltas = {key: float(a[key].cost_usd) - float(b[key].cost_usd) for key in a}
    by_case: dict[str, list[float]] = {}
    for key, delta in deltas.items():
        by_case.setdefault(a[key].case_id, []).append(delta)
    case_deltas = [statistics.mean(values) for values in by_case.values()]
    rng = random.Random(seed)
    n_cases = len(case_deltas)
    draws = sorted(
        statistics.mean(case_deltas[rng.randrange(n_cases)] for _ in range(n_cases))
        for _ in range(n_resamples)
    )
    tail = (1 - confidence) / 2
    low = draws[max(0, int(tail * n_resamples) - 1)]
    high = draws[min(n_resamples - 1, int((1 - tail) * n_resamples))]
    warning = None
    if n_cases < MIN_USEFUL_CLUSTERS:
        warning = (
            f"{n_cases} case clusters: paired cost interval is indicative only; "
            "adding repeats does not add independent cost diversity."
        )
    success_deltas = [deltas[key] for key in both_success]
    return PairedCostComparison(
        n_pairs=len(a), n_both_priced=len(both_priced),
        both_success_pairs=len(both_success), available=True,
        mean_delta_usd=statistics.mean(deltas.values()),
        median_delta_usd=statistics.median(deltas.values()),
        case_macro_delta_usd=statistics.mean(case_deltas),
        case_macro_delta_low_usd=low, case_macro_delta_high_usd=high,
        both_success_mean_delta_usd=(statistics.mean(success_deltas) if success_deltas else None),
        n_case_clusters=n_cases, resamples=n_resamples, confidence=confidence,
        warning=warning, reason=None,
    )
