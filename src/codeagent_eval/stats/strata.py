"""Case-macro stratified rates for heterogeneous benchmark slices.

Repeats measure reliability inside one case; they do not create new task diversity. A stratum
therefore averages each case's trial rate first, then averages the cases. Pooling every trial
would silently give cases with more repeats more weight.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class StratumResult:
    stratum: str
    case_count: int
    trial_count: int
    macro_average: float


def stratified_macro_average(
    outcomes: dict[str, list[bool | float]], strata: dict[str, str]
) -> list[StratumResult]:
    """Group case outcomes by a declared stratum and average cases, not trials."""
    if not outcomes:
        return []
    missing = sorted(set(outcomes) - set(strata))
    if missing:
        raise ValueError(f"missing strata for cases: {missing}")

    grouped: dict[str, list[tuple[float, int]]] = {}
    for case_id, values in outcomes.items():
        if not values:
            continue
        rate = statistics.mean(float(value) for value in values)
        grouped.setdefault(strata[case_id], []).append((rate, len(values)))

    return [
        StratumResult(
            stratum=name,
            case_count=len(cases),
            trial_count=sum(count for _, count in cases),
            macro_average=statistics.mean(rate for rate, _ in cases),
        )
        for name, cases in sorted(grouped.items())
    ]
