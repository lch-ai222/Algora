"""Cluster bootstrap intervals, where the cluster is a case rather than a trial.

Repeats of one case are not independent observations: they share the same defect, the same
instructions and the same reference solution, so a run that is easy for an agent is easy on
every repeat. Resampling trials would treat 12 correlated outcomes as 12 independent ones and
report an interval roughly a factor of sqrt(repeats) too narrow. Resampling *cases* keeps the
correlation inside the unit being resampled.

The consequence is uncomfortable and worth stating plainly: interval width is governed by the
number of cases, not the number of repeats. A suite of four cases cannot support a tight
interval no matter how many times each one is run — so this module warns rather than quietly
returning a number that looks more precise than the design allows.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

#: Below this, the resampling distribution is too coarse for the interval to mean much:
#: four clusters admit only 35 distinct resamples, so the bounds land on a handful of values.
MIN_USEFUL_CLUSTERS = 8


@dataclass(frozen=True)
class Cluster:
    """One case and the binary trial outcomes recorded inside it."""

    key: str
    outcomes: tuple[bool, ...]

    @property
    def rate(self) -> float:
        return sum(self.outcomes) / len(self.outcomes) if self.outcomes else 0.0


@dataclass(frozen=True)
class BootstrapResult:
    point: float
    low: float
    high: float
    n_clusters: int
    n_observations: int
    resamples: int
    confidence: float
    #: Present when the design cannot support the interval it just produced.
    warning: str | None = None

    @property
    def width(self) -> float:
        return self.high - self.low


def suite_rate(clusters: list[Cluster]) -> float:
    """Mean of per-case rates — the same statistic the runner reports as suite success.

    Deliberately not the pooled trial mean: that would weight a case with more repeats more
    heavily, which is a property of the schedule rather than of the benchmark.
    """
    return statistics.mean(c.rate for c in clusters) if clusters else 0.0


def cluster_bootstrap_ci(
    clusters: list[Cluster],
    *,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> BootstrapResult:
    """Percentile bootstrap over whole cases.

    ``seed`` is fixed by default: an interval that moves between two runs of the same analysis
    is not something a report can cite.
    """
    if not clusters:
        raise ValueError("cannot bootstrap an empty sample")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")

    rng = random.Random(seed)
    n = len(clusters)
    point = suite_rate(clusters)

    draws = sorted(
        suite_rate([clusters[rng.randrange(n)] for _ in range(n)]) for _ in range(n_resamples)
    )
    tail = (1 - confidence) / 2
    low = draws[max(0, int(tail * n_resamples) - 1)]
    high = draws[min(n_resamples - 1, int((1 - tail) * n_resamples))]

    warning = None
    if n < MIN_USEFUL_CLUSTERS:
        warning = (
            f"{n} clusters: the resampling distribution is coarse and the interval is "
            f"indicative only. Adding cases narrows it; adding repeats does not."
        )

    return BootstrapResult(
        point=point,
        low=low,
        high=high,
        n_clusters=n,
        n_observations=sum(len(c.outcomes) for c in clusters),
        resamples=n_resamples,
        confidence=confidence,
        warning=warning,
    )
