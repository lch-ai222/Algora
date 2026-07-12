#!/usr/bin/env python
"""Print a Version Compare between two experiment runs.

    python scripts/compare_runs.py <baseline_run_dir> <candidate_run_dir>

Each argument is an experiment dir (or its summary.json). Shows suite-level Task/Strict deltas
and the improved / regressed / stable buckets — the V1→V2 story.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.compare import compare_experiments, load_summary  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _sign(x: float) -> str:
    color = GREEN if x > 0 else RED if x < 0 else DIM
    return f"{color}{x:+.2f}{RESET}"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    baseline = load_summary(sys.argv[1])
    candidate = load_summary(sys.argv[2])
    cmp = compare_experiments(baseline, candidate)

    print(f"Version Compare: {cmp['baseline_id']}  →  {cmp['candidate_id']}  (suite: {cmp['suite']})")
    bt, ct = cmp["baseline_task"], cmp["candidate_task"]
    bs, cs = cmp["baseline_strict"], cmp["candidate_strict"]
    print(f"  Task Success   {bt:.2f} → {ct:.2f}   Δ {_sign(cmp['suite_task_delta'])}")
    print(f"  Strict Success {bs:.2f} → {cs:.2f}   Δ {_sign(cmp['suite_strict_delta'])}")
    print(f"\n  improved={len(cmp['improved'])}  regressed={len(cmp['regressed'])}  stable={len(cmp['stable'])}")
    print(f"\n  {'case':<28} {'task':>14} {'strict':>14} {'tools':>8}  status")
    for r in cmp["cases"]:
        mark = {"improved": GREEN, "regressed": RED, "stable": DIM}[r["status"]]
        print(
            f"  {r['case_id']:<28} "
            f"{r['baseline_task']:.2f}->{r['candidate_task']:.2f} "
            f"   {r['baseline_strict']:.2f}->{r['candidate_strict']:.2f} "
            f"   {_sign(r['tool_calls_delta'])}  {mark}{r['status']}{RESET}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
