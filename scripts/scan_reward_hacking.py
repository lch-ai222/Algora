#!/usr/bin/env python3
"""Scan every patch already collected for signs that verification was disarmed.

Detection needs no new experiments: every trial ever run left its diff on disk, so the
question "how often does this happen" can be answered against the runs that already exist —
including the external agent's, which makes the rate comparable across frameworks.

A zero result is reported as a Wilson upper bound rather than as absence. "0 out of N" does
not show the behaviour cannot occur; it bounds how common it could be given the sample, and
that distinction is the whole reason the detector is validated separately (see
``tests/test_reward_hacking.py``: hand-written hacks must all fire, reference solutions must
all stay clean).

    python scripts/scan_reward_hacking.py artifacts/runs
    python scripts/scan_reward_hacking.py artifacts/runs /tmp/other-runs --json report.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

from codeagent_eval.detectors import detect_reward_hacking
from codeagent_eval.stats import wilson_interval


def scan_trial(trial_dir: Path) -> dict[str, Any] | None:
    """Scan one trial directory, or return None when it holds no gradeable patch."""
    patch_file = trial_dir / "patch.diff"
    if not patch_file.is_file():
        return None
    patch = patch_file.read_text(errors="replace")
    if not patch.strip():
        return None

    config = {}
    config_file = trial_dir / "config.json"
    if config_file.is_file():
        try:
            config = json.loads(config_file.read_text())
        except ValueError:
            config = {}

    # Whether the agent could have edited tests at all. The MiniAgent's sandbox refuses the
    # write outright, so a zero from those trials is enforcement rather than observation, and
    # pooling the two would turn a policy into a finding.
    unconstrained = False
    trial_file = trial_dir / "trial.json"
    if trial_file.is_file():
        try:
            checks = json.loads(trial_file.read_text()).get("completion_checks", {})
            unconstrained = checks.get("command_policy_enforced") is False
        except ValueError:
            pass

    report = detect_reward_hacking(patch)
    return {
        "trial": str(trial_dir),
        "unconstrained": unconstrained,
        "agent": config.get("agent"),
        "adapter": config.get("adapter"),
        "model": config.get("model"),
        "case_id": config.get("case_id") or trial_dir.parent.name,
        "hacked": report.hacked,
        "strongest_severity": report.strongest_severity,
        "signals": [s.model_dump() for s in report.signals],
    }


def scan(roots: list[Path]) -> list[dict[str, Any]]:
    results = []
    for root in roots:
        for patch_file in sorted(root.rglob("patch.diff")):
            found = scan_trial(patch_file.parent)
            if found is not None:
                results.append(found)
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    hacked = [r for r in results if r["hacked"]]
    low, high = wilson_interval(len(hacked), n)

    # The only sample that measures behaviour: trials where nothing stopped the agent.
    free = [r for r in results if r["unconstrained"]]
    free_hacked = [r for r in free if r["hacked"]]
    free_low, free_high = wilson_interval(len(free_hacked), len(free))

    by_agent: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"n": 0, "hacked": 0})
    for r in results:
        bucket = by_agent[str(r.get("adapter") or r.get("agent") or "unknown")]
        bucket["n"] += 1
        bucket["hacked"] += int(r["hacked"])

    signal_counts = collections.Counter(
        s["name"] for r in results for s in r["signals"]
    )
    return {
        "patches_scanned": n,
        "strong_findings": len(hacked),
        "rate": round(len(hacked) / n, 6) if n else None,
        "rate_ci95": [round(low, 6), round(high, 6)],
        "unconstrained_patches": len(free),
        "unconstrained_findings": len(free_hacked),
        "unconstrained_rate_ci95": [round(free_low, 6), round(free_high, 6)],
        "by_agent": {k: dict(v) for k, v in sorted(by_agent.items())},
        "signal_counts": dict(signal_counts.most_common()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("roots", nargs="+", type=Path, help="directories holding trial artifacts")
    parser.add_argument("--json", type=Path, default=None, help="write the full findings here")
    parser.add_argument(
        "--fail-on-detection",
        action="store_true",
        help="exit non-zero if any strong signal fired (for CI gating)",
    )
    args = parser.parse_args(argv)

    results = scan(args.roots)
    if not results:
        print("no patches found; nothing to scan", file=sys.stderr)
        return 1

    summary = summarize(results)
    print(f"scanned {summary['patches_scanned']} patches from {len(args.roots)} root(s)")
    print(f"strong findings: {summary['strong_findings']}")
    low, high = summary["rate_ci95"]
    if summary["strong_findings"] == 0:
        # The sentence this whole script exists to be able to say honestly.
        print(f"  rate 0/{summary['patches_scanned']}; 95% upper bound {high * 100:.2f}% "
              "— not observed, not proven absent")
    else:
        print(f"  rate {summary['rate'] * 100:.2f}%  95% CI [{low * 100:.2f}%, {high * 100:.2f}%]")

    free_n = summary["unconstrained_patches"]
    print(f"\nof those, {free_n} came from trials where the harness did not block test edits")
    if free_n:
        f_high = summary["unconstrained_rate_ci95"][1]
        print(f"  {summary['unconstrained_findings']}/{free_n}; 95% upper bound {f_high * 100:.1f}%"
              " — this is the sample that measures behaviour rather than policy")
    else:
        print("  none: every scanned trial ran under a harness that forbids editing tests,")
        print("  so the overall zero reflects enforcement and cannot be read as a rate")

    print("\nby agent:")
    for agent, counts in summary["by_agent"].items():
        print(f"  {agent:<16} {counts['hacked']}/{counts['n']}")

    print("\nsignals seen (including informational ones that are not accusations):")
    for name, count in summary["signal_counts"].items() or [("(none)", 0)]:
        print(f"  {name:<24} {count}")

    for r in results:
        if r["hacked"]:
            print(f"\nFINDING {r['case_id']} [{r.get('adapter')}] {r['trial']}")
            for signal in r["signals"]:
                if signal["severity"] != "strong":
                    continue
                print(f"  {signal['name']}: {signal['description']}")
                for e in signal["evidence"][:5]:
                    print(f"    {e['file']}: {e['line']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
        print(f"\nFull findings: {args.json}")

    return 2 if (args.fail_on_detection and summary["strong_findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
