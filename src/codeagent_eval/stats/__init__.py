"""Statistics for reporting evaluation results honestly."""

from codeagent_eval.stats.bootstrap import (
    MIN_USEFUL_CLUSTERS,
    BootstrapResult,
    Cluster,
    cluster_bootstrap_ci,
    suite_rate,
)
from codeagent_eval.stats.intervals import wilson_interval
from codeagent_eval.stats.mcnemar import (
    PairedComparison,
    UnpairedSamples,
    exact_mcnemar_p,
    paired_comparison,
)

__all__ = [
    "MIN_USEFUL_CLUSTERS",
    "BootstrapResult",
    "Cluster",
    "PairedComparison",
    "UnpairedSamples",
    "cluster_bootstrap_ci",
    "exact_mcnemar_p",
    "paired_comparison",
    "suite_rate",
    "wilson_interval",
]
