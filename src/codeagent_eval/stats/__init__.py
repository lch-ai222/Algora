"""Statistics for reporting evaluation results honestly."""

from codeagent_eval.stats.bootstrap import (
    MIN_USEFUL_CLUSTERS,
    BootstrapResult,
    Cluster,
    cluster_bootstrap_ci,
    suite_rate,
)
from codeagent_eval.stats.costs import (
    CostObservation,
    CostSummary,
    PairedCostComparison,
    paired_cost_comparison,
    summarize_costs,
)
from codeagent_eval.stats.intervals import wilson_interval
from codeagent_eval.stats.mcnemar import (
    PairedComparison,
    UnpairedSamples,
    exact_mcnemar_p,
    paired_comparison,
)
from codeagent_eval.stats.strata import StratumResult, stratified_macro_average

__all__ = [
    "MIN_USEFUL_CLUSTERS",
    "BootstrapResult",
    "Cluster",
    "CostObservation",
    "CostSummary",
    "PairedComparison",
    "PairedCostComparison",
    "StratumResult",
    "UnpairedSamples",
    "cluster_bootstrap_ci",
    "exact_mcnemar_p",
    "paired_comparison",
    "paired_cost_comparison",
    "stratified_macro_average",
    "summarize_costs",
    "suite_rate",
    "wilson_interval",
]
