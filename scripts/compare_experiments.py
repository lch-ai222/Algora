#!/usr/bin/env python3
"""Compare two experiments with an interval and a paired test instead of two point estimates.

Every arm in this project runs the same cases at the same repeat indices, so the comparison is
paired by construction. Reporting only "0.50 vs 1.00" discards that structure and says nothing
about how much of the gap the sample can actually support.

Two things this prints that a bare summary cannot:

* a **cluster bootstrap interval** per arm, resampling cases rather than trials, because
  repeats of one case are correlated and treating them as independent narrows the interval by
  roughly sqrt(repeats);
* an **exact McNemar** test over the trials where the arms disagreed, since concordant trials
  carry no information about which arm is better.

    python scripts/compare_experiments.py artifacts/runs/<a> artifacts/runs/<b>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codeagent_eval.stats import (
    Cluster,
    UnpairedSamples,
    cluster_bootstrap_ci,
    paired_comparison,
)

METRICS = ("task_success", "strict_success")


def load_outcomes(experiment: Path, metric: str) -> tuple[dict[str, bool], list[Cluster]]:
    """Read one experiment's per-trial outcomes, keyed by ``case_id/repN``.

    Infra-invalid trials are dropped: a provider failure is missing evidence, and pairing it
    against a real result on the other arm would compare an outage to a capability.
    """
    per_trial: dict[str, bool] = {}
    per_case: dict[str, list[bool]] = {}

    for grade_file in sorted(experiment.rglob("grader-results.json")):
        trial_dir = grade_file.parent
        trial_file = trial_dir / "trial.json"
        if trial_file.is_file():
            checks = json.loads(trial_file.read_text()).get("completion_checks", {})
            if checks.get("provider_error"):
                continue
        grade = json.loads(grade_file.read_text())
        case_id = trial_dir.parent.name
        key = f"{case_id}/{trial_dir.name}"
        outcome = bool(grade[metric])
        per_trial[key] = outcome
        per_case.setdefault(case_id, []).append(outcome)

    clusters = [Cluster(key=k, outcomes=tuple(v)) for k, v in sorted(per_case.items())]
    return per_trial, clusters


def _fingerprint(experiment: Path) -> str | None:
    summary_file = experiment / "summary.json"
    if not summary_file.is_file():
        return None
    return json.loads(summary_file.read_text()).get("run_config", {}).get("suite_fingerprint")


def describe(experiment: Path) -> str:
    summary_file = experiment / "summary.json"
    if not summary_file.is_file():
        return experiment.name
    s = json.loads(summary_file.read_text())
    cfg = s.get("run_config", {})
    bits = [str(s.get("agent")), str(cfg.get("model") or "—")]
    if cfg.get("max_wall_clock_override"):
        bits.append(f"{cfg['max_wall_clock_override']}s")
    if cfg.get("max_steps_override"):
        bits.append(f"{cfg['max_steps_override']} steps")
    if cfg.get("ablate"):
        bits.append("−" + ",".join(cfg["ablate"]))
    return " ".join(bits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--resamples", type=int, default=10_000)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    label_a, label_b = describe(args.a), describe(args.b)
    print(f"A: {label_a}\nB: {label_b}\n")

    # A comparison spanning a change to the benchmark is not a comparison of the arms. Both
    # sides recording the suite's name told nobody that four cases and twenty-two repository
    # files had been added between two runs, and the disagreement that followed could not be
    # attributed to either sampling or content.
    prints = [_fingerprint(args.a), _fingerprint(args.b)]
    if all(prints) and prints[0] != prints[1]:
        print(f"⚠ the two runs saw different benchmark content: {prints[0]} vs {prints[1]}.")
        print("  Differences below mix the arms with the change to the suite; rerun the older")
        print("  arm against the current suite before reading them as a comparison.\n")
    elif not all(prints):
        print("⚠ at least one run predates suite fingerprinting; its benchmark content is")
        print("  unverifiable and a difference may be the suite rather than the arm.\n")

    report: dict[str, object] = {"a": label_a, "b": label_b, "metrics": {}}
    for metric in METRICS:
        trials_a, clusters_a = load_outcomes(args.a, metric)
        trials_b, clusters_b = load_outcomes(args.b, metric)
        if not trials_a or not trials_b:
            print(f"{metric}: no gradeable trials", file=sys.stderr)
            return 1

        ci_a = cluster_bootstrap_ci(clusters_a, n_resamples=args.resamples)
        ci_b = cluster_bootstrap_ci(clusters_b, n_resamples=args.resamples)

        print(f"── {metric} ──")
        for label, ci in ((label_a, ci_a), (label_b, ci_b)):
            print(f"  {label:<34} {ci.point:.3f}  95% CI [{ci.low:.3f}, {ci.high:.3f}]"
                  f"  ({ci.n_clusters} cases, {ci.n_observations} trials)")

        try:
            pair = paired_comparison(trials_a, trials_b, label_a=label_a, label_b=label_b)
        except UnpairedSamples as exc:
            print(f"  paired test skipped: {exc}\n")
            report["metrics"][metric] = {"a": vars(ci_a), "b": vars(ci_b), "paired": None}
            continue

        print(f"  difference {pair.difference:+.3f}   "
              f"discordant {pair.discordant}/{pair.n_pairs} "
              f"(A only {pair.a_only}, B only {pair.b_only})")
        verdict = "significant at 0.05" if pair.p_value < 0.05 else "not significant"
        print(f"  exact McNemar p = {pair.p_value:.4f}  — {verdict}")
        if pair.p_value >= 0.05:
            # The distinction this line exists to protect.
            print("    'not significant' means the sample is too small to rule out chance,")
            print("    not that the arms perform the same.")
        if ci_a.warning:
            print(f"  ⚠ {ci_a.warning}")
        print()

        report["metrics"][metric] = {
            "a": vars(ci_a),
            "b": vars(ci_b),
            "paired": vars(pair),
        }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
