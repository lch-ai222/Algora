"""Family-wise error control for a report that compares more than two arms.

Four arms produce six pairwise tests, and reading six p-values each against 0.05 is not the
same thing as one test at 0.05: under a global null the chance of at least one falling below
the threshold is 1 - 0.95^6, about 26%. A cross-agent report is exactly the setting where that
matters, because the interesting claim is usually "this arm differs from the others" — which is
the claim built out of every pairwise test at once.

Holm rather than Bonferroni: it controls the same family-wise error rate under no additional
assumptions and is uniformly more powerful, so there is no reason to pay Bonferroni's price.
The step-down enforcement is not cosmetic — without it the adjusted values can decrease as raw
p rises, and a reader comparing two rows would see the ordering invert.

Both values are reported. The raw p-value is what the paired test computed and stays auditable;
the adjusted one is what a claim about the family should be read against.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdjustedComparison:
    """One test's raw and family-adjusted p-value, plus where it sat in the family."""

    key: str
    p_value: float
    p_adjusted: float
    rank: int
    n_comparisons: int

    def significant(self, alpha: float = 0.05) -> bool:
        return self.p_adjusted < alpha


def holm_adjust(p_values: dict[str, float]) -> dict[str, AdjustedComparison]:
    """Holm-Bonferroni step-down adjustment over a family of tests.

    A single test is returned unchanged: there is no family to correct for, and inflating a
    lone p-value would be as wrong as leaving six uncorrected.
    """
    if not p_values:
        return {}
    for key, value in p_values.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"p-value for {key!r} outside [0, 1]: {value}")

    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    n = len(ordered)

    adjusted: dict[str, AdjustedComparison] = {}
    running = 0.0
    for index, (key, raw) in enumerate(ordered):
        # Step-down: each adjusted value is monotone non-decreasing in rank, so the ordering a
        # reader sees matches the ordering of the raw p-values.
        running = max(running, min(1.0, (n - index) * raw))
        adjusted[key] = AdjustedComparison(
            key=key,
            p_value=raw,
            p_adjusted=running,
            rank=index + 1,
            n_comparisons=n,
        )
    return adjusted


def family_wise_error_rate(n_comparisons: int, alpha: float = 0.05) -> float:
    """Chance of at least one false positive if a family of tests is read uncorrected.

    Reported next to the correction so the reason for it is a number rather than an assertion.
    """
    if n_comparisons < 0:
        raise ValueError("n_comparisons must be non-negative")
    return 1.0 - (1.0 - alpha) ** n_comparisons
