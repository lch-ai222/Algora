#!/usr/bin/env python
"""Meta-evaluate the code-review LLM-Judge against the human gold set.

    python scripts/run_judge_meta_eval.py

Runs the judge on each gold case, scores per-dimension agreement + Cohen's kappa vs the human
labels, and prints the trust map (dimensions below kappa/agreement threshold are downgraded from
hard gate to advisory). Writes the report JSON. Needs an LLM provider in .env.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.judge.gold import load_gold, provider_judge_fn, run_meta_eval  # noqa: E402
from codeagent_eval.judge.meta_eval import save_meta_eval_report  # noqa: E402
from codeagent_eval.llm import LlmProvider  # noqa: E402
from codeagent_eval.settings import load_settings  # noqa: E402

GOLD = _ROOT / "data" / "judge_gold" / "code_review_gold.jsonl"
REPORT = _ROOT / "data" / "judge_gold" / "meta_eval_report.json"
GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def main() -> int:
    provider = LlmProvider(load_settings())
    if not provider.enabled:
        print(f"ERROR: needs an LLM provider. {provider._availability_error()}", file=sys.stderr)
        return 2

    gold = load_gold(GOLD)
    n_items = sum(len(c.items) for c in gold)
    print(f"Meta-evaluating judge on {len(gold)} gold cases ({n_items} labeled items)…")

    report = run_meta_eval(gold, provider_judge_fn(provider), llm_used=True)
    print(f"\n  {'dimension':<16} {'n':>3} {'agreement':>10} {'kappa':>8}  trust")
    for d in report.dimensions:
        color = GREEN if d.trusted else RED
        agr = f"{d.agreement_rate:.2f}" if d.agreement_rate is not None else "—"
        kap = f"{d.cohen_kappa:.2f}" if d.cohen_kappa is not None else "—"
        trust = "gate" if d.trusted else "advisory (downgraded)"
        print(f"  {d.dimension:<16} {d.sample_count:>3} {agr:>10} {kap:>8}  {color}{trust}{RESET}")
        if d.downgrade_reason:
            print(f"      ↳ {d.downgrade_reason}")

    save_meta_eval_report(report, REPORT)
    print(f"\nReport: {REPORT}")
    print(f"Trust map: {report.trust_map()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
