#!/usr/bin/env python3
"""Benchmark health gate: the deterministic bounds must hold end-to-end.

``selfcheck.py`` validates each case in isolation (target fails on base, defect isolated,
reference fix passes everything, hidden tests unreadable). This script checks the *pipeline*:
running the reference tier over a suite must score 1.00 and the no-op tier must score 0.00.

Those two numbers are the discrimination floor and ceiling. If either drifts, every agent
number measured against the suite becomes uninterpretable — a reference below 1.00 means the
suite is unsolvable or the grader is broken, and a none above 0.00 means a case passes without
any work. Both are silent failures that a passing unit-test suite would not catch, which is
why this runs in CI rather than living in a runbook.

    python scripts/check_bounds.py --suite datasets/mini_store_suite
    python scripts/check_bounds.py --suite datasets/mini_store_long --out artifacts/ci
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from codeagent_eval.runner import run_experiment

EXPECTED = {"reference": 1.0, "none": 0.0}


def check_suite(suite_dir: Path, out_root: Path, *, keep: bool = False) -> list[str]:
    """Run both deterministic tiers over ``suite_dir``; return a list of failure messages."""
    failures: list[str] = []
    for tier, expected in EXPECTED.items():
        summary = run_experiment(tier, suite_dir, None, 1, None, out_root)

        actual = summary["suite_task_success"]
        if actual is None or abs(actual - expected) > 1e-9:
            failures.append(
                f"{suite_dir.name}/{tier}: suite_task_success={actual} expected {expected}"
            )
        if summary["infra_failures"]:
            failures.append(
                f"{suite_dir.name}/{tier}: {summary['infra_failures']} infra failures "
                "(the harness broke; the score is not evidence either way)"
            )
        # A tier-level average can hide a compensating pair of cases, so pin every case too.
        for case in summary["cases"]:
            rate = case["task_success_rate"]
            if rate is None or abs(rate - expected) > 1e-9:
                failures.append(
                    f"{suite_dir.name}/{tier}/{case['case_id']}: task_success_rate={rate} "
                    f"expected {expected}"
                )
        if not keep:
            shutil.rmtree(out_root / summary["experiment_id"], ignore_errors=True)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--suite", action="append", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/bounds"))
    parser.add_argument("--keep", action="store_true", help="retain the produced experiments")
    args = parser.parse_args(argv)

    failures: list[str] = []
    for suite_dir in args.suite:
        failures.extend(check_suite(suite_dir, args.out, keep=args.keep))

    if failures:
        print("\nFAILED: deterministic bounds violated", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"\nOK: reference=1.00 / none=0.00 hold for {len(args.suite)} suite(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
