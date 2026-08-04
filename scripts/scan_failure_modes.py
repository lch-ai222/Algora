#!/usr/bin/env python3
"""Scan every trial already collected for failure modes the pass/fail oracle cannot see.

Two detectors run over the artifacts:

* **reward hacking** — a patch that disarms verification instead of satisfying it;
* **instruction drift** — a constraint broken partway through, including breaches the agent
  undid before finishing, which the final-state grader cannot see at all.

Neither needs new experiments: every trial ever run left its diff and its trajectory on disk,
so "how often does this happen" can be answered against the runs that already exist —
including the external agent's, which makes the rates comparable across frameworks.

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

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import load_suite
from codeagent_eval.detectors import (
    detect_context_amnesia,
    detect_instruction_drift,
    detect_reward_hacking,
)
from codeagent_eval.stats import wilson_interval

#: Cases are looked up by id across the shipped suites, since a trial artifact records the id
#: but not which suite it came from.
_CASES: dict[str, Any] = {}


def _case(case_id: str):
    if not _CASES:
        for suite_dir in sorted(Path("datasets").glob("*/suite.json")):
            try:
                for c in load_suite(suite_dir.parent).cases:
                    _CASES.setdefault(c.case_id, c)
            except (OSError, ValueError):
                continue
    return _CASES.get(case_id)


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

    # Instruction drift needs the trajectory and the case's constraints; a trial whose case is
    # no longer in the shipped suites is scanned for hacking only rather than guessed at.
    drift = None
    amnesia = None
    case_id = config.get("case_id") or trial_dir.parent.name
    case = _case(case_id)
    trajectory = trial_dir / "trajectory.jsonl"
    if case is not None and trajectory.is_file():
        try:
            events = [json.loads(line) for line in trajectory.read_text().splitlines() if line.strip()]
            trial = TrialResult.model_validate(
                {**json.loads((trial_dir / "trial.json").read_text()), "events": events}
            )
            drift = detect_instruction_drift(case, trial).model_dump()
            amnesia = detect_context_amnesia(case, trial).model_dump()
        except (OSError, ValueError):
            drift = None

    return {
        "trial": str(trial_dir),
        "unconstrained": unconstrained,
        "drift": drift,
        "amnesia": amnesia,
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

    canaried = [r for r in results if (r.get("amnesia") or {}).get("edits_observed")]
    split_able = [r for r in canaried if r["amnesia"]["early_recall"] is not None]
    scanned_drift = [r for r in results if r["drift"] is not None]
    free_drift = [r for r in scanned_drift if r["unconstrained"]]
    free_drifted = [r for r in free_drift if r["drift"]["breaches"]]
    drifted = [r for r in scanned_drift if r["drift"]["breaches"]]
    self_corrected = [r for r in drifted if r["drift"]["self_corrected"]]
    persisted = [r for r in drifted if r["drift"]["persisted"]]
    constraint_counts = collections.Counter(
        b["constraint"] for r in drifted for b in r["drift"]["breaches"]
    )
    return {
        "canary_trials": len(canaried),
        "canary_edits": sum(r["amnesia"]["edits_observed"] for r in canaried),
        "canary_recall": (
            round(sum(r["amnesia"]["recall"] for r in canaried) / len(canaried), 4)
            if canaried else None
        ),
        "canary_decay": (
            round(
                sum(r["amnesia"]["early_recall"] - r["amnesia"]["late_recall"] for r in split_able)
                / len(split_able), 4
            ) if split_able else None
        ),
        "canary_split_trials": len(split_able),
        "drift_scanned": len(scanned_drift),
        "drift_unconstrained_scanned": len(free_drift),
        "drift_unconstrained_trials": len(free_drifted),
        "drift_trials": len(drifted),
        "drift_self_corrected": len(self_corrected),
        "drift_persisted": len(persisted),
        "drift_constraints": dict(constraint_counts.most_common()),
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

    scanned = summary["drift_scanned"]
    print(f"\ninstruction drift: {summary['drift_trials']}/{scanned} trials broke a constraint")
    free_scanned = summary["drift_unconstrained_scanned"]
    # Same split as above, and for the same reason. The MiniAgent's sandbox refuses writes to
    # forbidden paths and denied commands outright, so only its file-count constraint is a free
    # observation; an unblocked agent is measured on all three.
    print(f"  {summary['drift_unconstrained_trials']}/{free_scanned} of these came from trials "
          "where path and command rules were not pre-blocked by the harness")
    print("  (for the MiniAgent only the changed-file limit is freely observed; paths and "
          "commands are enforced)")
    if summary["drift_trials"]:
        print(f"  {summary['drift_persisted']} shipped the breach "
              f"(the only kind the final-state grader sees)")
        print(f"  {summary['drift_self_corrected']} took it back before finishing "
              f"— invisible without replaying the trajectory")
        for name, count in summary["drift_constraints"].items():
            print(f"    {name:<22} {count}")

    if summary["canary_trials"]:
        print(f"\ncontext amnesia: {summary['canary_edits']} edits across "
              f"{summary['canary_trials']} trials carrying a canary")
        print(f"  adherence {summary['canary_recall']:.3f}; mean early−late decay "
              f"{summary['canary_decay']:+.3f} over {summary['canary_split_trials']} trials "
              "long enough to split")
        print("  (uniform failure would mean the rule was never understood; only a late drop "
              "is amnesia)")

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
