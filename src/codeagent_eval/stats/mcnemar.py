"""Exact McNemar for two harnesses run over the same trials.

Every comparison in this project is paired by construction: the arms see the same cases, the
same repeat indices, the same budget. A two-sample test throws that away and asks a weaker
question, so the paired test is both more appropriate and more powerful — the discordant pairs
are where all the information about a difference lives.

Exact rather than the chi-square approximation because the discordant counts here are small.
With four or five disagreements the asymptotic statistic is simply wrong, and a p-value
computed the wrong way is worse than none.

Pairing is verified rather than assumed. Two experiments that do not cover the same trial grid
are refused instead of being lined up by position, which would silently compare unrelated
trials and produce a number that looks fine.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb


@dataclass(frozen=True)
class PairedComparison:
    """The 2x2 table of two arms over the same trials, plus the exact test."""

    n_pairs: int
    both: int
    neither: int
    a_only: int
    b_only: int
    p_value: float
    rate_a: float
    rate_b: float

    @property
    def discordant(self) -> int:
        return self.a_only + self.b_only

    @property
    def difference(self) -> float:
        return self.rate_a - self.rate_b


class UnpairedSamples(ValueError):
    """Raised when the two arms do not cover the same trials."""


def exact_mcnemar_p(a_only: int, b_only: int) -> float:
    """Two-sided exact p-value: a sign test on the discordant pairs.

    Returns 1.0 when nothing disagrees — with no discordant pairs there is no evidence of a
    difference in either direction, which is not the same as evidence of equivalence.
    """
    if a_only < 0 or b_only < 0:
        raise ValueError("counts must be non-negative")
    n = a_only + b_only
    if n == 0:
        return 1.0

    smaller = min(a_only, b_only)
    tail = sum(comb(n, i) for i in range(smaller + 1)) * 0.5**n
    return min(1.0, 2 * tail)


def paired_comparison(
    a: dict[str, bool], b: dict[str, bool], *, label_a: str = "A", label_b: str = "B"
) -> PairedComparison:
    """Compare two arms keyed by trial id (``case_id/rep``).

    Both mappings must have identical key sets; a mismatch means the arms did not run the same
    grid and the pairing would be fictional.
    """
    if a.keys() != b.keys():
        missing_b = sorted(a.keys() - b.keys())[:3]
        missing_a = sorted(b.keys() - a.keys())[:3]
        raise UnpairedSamples(
            f"{label_a} and {label_b} do not cover the same trials; "
            f"missing from {label_b}: {missing_b}, missing from {label_a}: {missing_a}"
        )
    if not a:
        raise UnpairedSamples("no trials to compare")

    both = sum(1 for k in a if a[k] and b[k])
    neither = sum(1 for k in a if not a[k] and not b[k])
    a_only = sum(1 for k in a if a[k] and not b[k])
    b_only = sum(1 for k in a if not a[k] and b[k])

    return PairedComparison(
        n_pairs=len(a),
        both=both,
        neither=neither,
        a_only=a_only,
        b_only=b_only,
        p_value=exact_mcnemar_p(a_only, b_only),
        rate_a=sum(a.values()) / len(a),
        rate_b=sum(b.values()) / len(b),
    )
