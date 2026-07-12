#!/usr/bin/env python
"""Run the SWE-bench compatibility sample.

    python scripts/run_swebench.py --mode gold     # apply the reference patch (no LLM)
    python scripts/run_swebench.py --mode agent     # let the MiniAgent solve it (needs key)

Prints resolved / FAIL_TO_PASS / PASS_TO_PASS per instance. This is a COMPATIBILITY SAMPLE in
SWE-bench format (small self-contained repo), not an official leaderboard instance — real
instances plug into the same schema; see docs/swebench_and_docker.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.benchmark.swebench import load_instances, run_instance  # noqa: E402

SUITE = _ROOT / "datasets" / "swebench_compat"
GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gold", "agent"], default="gold")
    parser.add_argument("--agent-version", choices=["v1", "v2"], default="v2")
    args = parser.parse_args()

    provider = None
    if args.mode == "agent":
        from codeagent_eval.llm import LlmProvider
        from codeagent_eval.settings import load_settings

        provider = LlmProvider(load_settings())
        if not provider.enabled:
            print(f"ERROR: mode=agent needs an LLM provider. {provider._availability_error()}", file=sys.stderr)
            return 2

    instances = load_instances(SUITE / "instances.jsonl")
    print(f"SWE-bench Compatibility Sample — {len(instances)} instance(s), mode={args.mode}")
    resolved = 0
    for inst in instances:
        r = run_instance(inst, SUITE, mode=args.mode, provider=provider, agent_version=args.agent_version)
        resolved += r.resolved
        mark = f"{GREEN}RESOLVED{RESET}" if r.resolved else f"{RED}unresolved{RESET}"
        print(f"  [{mark}] {inst.instance_id}  "
              f"{DIM}FAIL_TO_PASS={r.fail_to_pass_passed} PASS_TO_PASS={r.pass_to_pass_passed}{RESET}")
    print(f"\nResolved: {resolved}/{len(instances)}   {DIM}(Compatibility Sample — not a leaderboard number){RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
