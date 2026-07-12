#!/usr/bin/env python
"""Run the HumanEval+ subset against the configured model.

    python scripts/run_humaneval.py [--limit N]

Prints Pass@1 / base / plus pass rates and writes summary.json under artifacts/runs/. Needs an
LLM provider configured in .env. Use --selfcheck to only verify the canonical solutions pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.benchmark.humaneval_plus import (  # noqa: E402
    load_problems,
    run_humaneval_suite,
    selfcheck_dataset,
)
from codeagent_eval.llm import LlmProvider  # noqa: E402
from codeagent_eval.models import utc_now_iso  # noqa: E402
from codeagent_eval.settings import load_settings  # noqa: E402

DATASET = _ROOT / "datasets" / "humaneval_plus" / "problems.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--selfcheck", action="store_true", help="only verify canonical solutions")
    args = parser.parse_args()

    problems = load_problems(DATASET)
    if args.limit:
        problems = problems[: args.limit]

    if args.selfcheck:
        bad = selfcheck_dataset(problems)
        print(f"canonical self-check: {len(problems) - len(bad)}/{len(problems)} pass base+plus")
        if bad:
            print("  FAILING:", bad)
        return 1 if bad else 0

    provider = LlmProvider(load_settings())
    if not provider.enabled:
        print(f"ERROR: needs an LLM provider. {provider._availability_error()}", file=sys.stderr)
        return 2

    print(f"Running HumanEval+ ({len(problems)} problems) on {provider.settings.llm_provider}…")
    summary = run_humaneval_suite(provider, problems)
    print(f"\n  Pass@1 (base)   {summary.pass_at_1:.2%}")
    print(f"  Plus pass rate  {summary.plus_pass_rate:.2%}")
    print(f"  timeout rate    {summary.timeout_rate:.2%}   error rate {summary.error_rate:.2%}")
    print(f"  mean latency    {summary.latency_ms_mean:.0f} ms")
    for r in summary.results:
        mark = "✓" if r.base_passed else "✗"
        plus = "＋" if r.plus_passed else " "
        print(f"    {mark}{plus} {r.task_id}")

    out = _ROOT / "artifacts" / "runs" / f"humaneval-{utc_now_iso().replace(':', '').replace('-', '')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary.model_dump(), indent=2))
    print(f"\nArtifacts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
