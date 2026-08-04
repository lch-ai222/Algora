"""B3: intervals and paired tests, and the design limits they must not hide.

The numbers this project reports are small-sample and paired. Both facts have a way of being
lost: an interval computed over trials instead of cases looks tighter than the design allows,
and a two-sample test on paired arms throws away the only information that distinguishes them.
"""

from __future__ import annotations

import pytest

from codeagent_eval.stats import (
    MIN_USEFUL_CLUSTERS,
    Cluster,
    UnpairedSamples,
    cluster_bootstrap_ci,
    exact_mcnemar_p,
    paired_comparison,
    suite_rate,
    wilson_interval,
)


def clusters(*rates_and_n) -> list[Cluster]:
    return [
        Cluster(key=f"case{i}", outcomes=tuple([True] * k + [False] * (n - k)))
        for i, (k, n) in enumerate(rates_and_n)
    ]


# --------------------------------------------------------------------------- #
# The cluster is the case
# --------------------------------------------------------------------------- #
def test_the_suite_rate_averages_cases_not_trials():
    """Pooling trials would weight a case with more repeats more heavily, which is a property
    of the schedule rather than of the benchmark."""
    uneven = [
        Cluster(key="a", outcomes=(True,) * 9 + (False,)),   # 0.9 over 10 trials
        Cluster(key="b", outcomes=(False,)),                  # 0.0 over 1 trial
    ]

    assert suite_rate(uneven) == pytest.approx(0.45)
    pooled = sum(sum(c.outcomes) for c in uneven) / sum(len(c.outcomes) for c in uneven)
    assert pooled == pytest.approx(9 / 11), "the pooled mean is the one we are avoiding"


def test_repeats_inside_a_case_do_not_narrow_the_interval():
    """The point of clustering: correlated repeats must not be counted as independent evidence."""
    few = cluster_bootstrap_ci(clusters((1, 1), (1, 1), (0, 1), (0, 1)))
    many = cluster_bootstrap_ci(clusters((10, 10), (10, 10), (0, 10), (0, 10)))

    assert few.point == many.point == pytest.approx(0.5)
    assert many.width == pytest.approx(few.width), "adding repeats must not buy precision"


def test_adding_cases_does_narrow_the_interval():
    four = cluster_bootstrap_ci(clusters(*[(1, 3)] * 2, *[(0, 3)] * 2))
    twenty = cluster_bootstrap_ci(clusters(*[(1, 3)] * 10, *[(0, 3)] * 10))

    assert twenty.width < four.width


def test_a_small_sample_says_so_instead_of_looking_precise():
    small = cluster_bootstrap_ci(clusters(*[(3, 3)] * 4))
    big = cluster_bootstrap_ci(clusters(*[(3, 3)] * (MIN_USEFUL_CLUSTERS + 2)))

    assert small.warning is not None and "clusters" in small.warning
    assert "Adding cases narrows it" in small.warning
    assert big.warning is None


def test_the_interval_is_reproducible():
    """An interval that moves between two runs of the same analysis cannot be cited."""
    sample = clusters((2, 3), (1, 3), (3, 3), (0, 3))

    assert cluster_bootstrap_ci(sample) == cluster_bootstrap_ci(sample)


def test_a_unanimous_sample_has_a_degenerate_interval():
    result = cluster_bootstrap_ci(clusters(*[(3, 3)] * 6))

    assert (result.point, result.low, result.high) == (1.0, 1.0, 1.0)


def test_bootstrapping_nothing_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="empty sample"):
        cluster_bootstrap_ci([])


def test_the_result_records_what_it_was_computed_from():
    result = cluster_bootstrap_ci(clusters((2, 3), (1, 3)), n_resamples=500, confidence=0.9)

    assert (result.n_clusters, result.n_observations) == (2, 6)
    assert (result.resamples, result.confidence) == (500, 0.9)


# --------------------------------------------------------------------------- #
# Paired comparison
# --------------------------------------------------------------------------- #
def test_only_the_disagreements_carry_information():
    """Trials both arms pass, or both fail, say nothing about which is better."""
    a = {f"c{i}/rep0": True for i in range(50)}
    b = dict(a)
    assert paired_comparison(a, b).p_value == 1.0

    a["c0/rep0"], b["c0/rep0"] = True, False
    assert paired_comparison(a, b).discordant == 1


def test_a_one_sided_disagreement_becomes_significant_only_with_enough_pairs():
    assert exact_mcnemar_p(4, 0) == pytest.approx(0.125)   # not significant
    assert exact_mcnemar_p(6, 0) == pytest.approx(0.03125)  # significant
    assert exact_mcnemar_p(3, 3) == pytest.approx(1.0)


def test_the_test_is_symmetric_in_the_two_arms():
    assert exact_mcnemar_p(5, 2) == exact_mcnemar_p(2, 5)


def test_no_disagreement_is_not_evidence_of_equivalence():
    assert exact_mcnemar_p(0, 0) == 1.0


def test_the_table_records_all_four_cells():
    a = {"x/rep0": True, "y/rep0": True, "z/rep0": False, "w/rep0": False}
    b = {"x/rep0": True, "y/rep0": False, "z/rep0": True, "w/rep0": False}

    result = paired_comparison(a, b)
    assert (result.both, result.neither, result.a_only, result.b_only) == (1, 1, 1, 1)
    assert result.n_pairs == 4
    assert result.difference == pytest.approx(0.0)


def test_arms_that_did_not_run_the_same_trials_are_refused():
    """Lining them up by position would compare unrelated trials and produce a number that
    looks fine."""
    a = {"c1/rep0": True, "c2/rep0": True}
    b = {"c1/rep0": True, "c3/rep0": True}

    with pytest.raises(UnpairedSamples, match="do not cover the same trials"):
        paired_comparison(a, b, label_a="v2", label_b="v3")


def test_comparing_nothing_is_refused():
    with pytest.raises(UnpairedSamples, match="no trials"):
        paired_comparison({}, {})


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        exact_mcnemar_p(-1, 2)


# --------------------------------------------------------------------------- #
# Wilson (used for zero-event detector results)
# --------------------------------------------------------------------------- #
def test_a_zero_is_bounded_rather_than_declared_absent():
    assert wilson_interval(0, 640)[1] < 0.01
    assert wilson_interval(0, 16)[1] > 0.15
