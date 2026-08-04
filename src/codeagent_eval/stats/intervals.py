"""Confidence intervals for rates, including the case that matters most: zero events.

A detector that fires zero times has not proved the behaviour absent — it has bounded how
common the behaviour could be given the sample. Reporting "0 out of 200" as "does not happen"
overstates the evidence; reporting it with a Wilson upper bound states exactly what was
observed and what it rules out.

Wilson rather than the normal approximation because the normal interval degenerates at 0 and
1, which is precisely where a detector's result usually lands.
"""

from __future__ import annotations

import math

#: Two-sided 95% normal quantile.
Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns ``(0.0, 0.0)`` for an empty sample: with no trials there is nothing to bound, and
    a full ``(0, 1)`` would read as a real, maximally wide finding.
    """
    if n <= 0:
        return (0.0, 0.0)
    if not 0 <= successes <= n:
        raise ValueError(f"successes={successes} out of range for n={n}")

    phat = successes / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    low, high = center - half, center + half
    # Snap the degenerate ends exactly: with no successes the lower bound is 0, and floating
    # point otherwise leaves a 1e-18 that reads as a real quantity in a report.
    if successes == 0:
        low = 0.0
    if successes == n:
        high = 1.0
    return (max(0.0, low), min(1.0, high))
