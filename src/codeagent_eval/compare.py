"""Version Compare — diff two experiment summaries (e.g. V1 vs V2) under identical conditions.

The M4 money shot: not a single aggregate number but the *distribution* of change — which
cases improved, which regressed, which stayed stable — plus shifts in cost/tooling. Same model,
same benchmark, same budget: the delta is attributable to the harness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _by_case(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["case_id"]: c for c in summary.get("cases", [])}


def _status(baseline_rate: float, candidate_rate: float) -> str:
    if candidate_rate > baseline_rate:
        return "improved"
    if candidate_rate < baseline_rate:
        return "regressed"
    return "stable"


def compare_experiments(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare two run summaries (as written to summary.json). Keyed on Task Success rate,
    with Strict Success and cost/tooling deltas alongside."""
    for label, summary in (("baseline", baseline), ("candidate", candidate)):
        if summary.get("infra_failures", 0):
            raise ValueError(f"cannot compare {label} with infrastructure-invalid trials")
        if summary.get("suite_task_success") is None or summary.get("suite_strict_success") is None:
            raise ValueError(f"cannot compare {label} without valid success metrics")

    b_cases, c_cases = _by_case(baseline), _by_case(candidate)
    shared = [cid for cid in b_cases if cid in c_cases]

    rows: list[dict[str, Any]] = []
    buckets: dict[str, list[str]] = {"improved": [], "regressed": [], "stable": []}
    for cid in shared:
        b, c = b_cases[cid], c_cases[cid]
        status = _status(b["task_success_rate"], c["task_success_rate"])
        buckets[status].append(cid)
        rows.append(
            {
                "case_id": cid,
                "baseline_task": b["task_success_rate"],
                "candidate_task": c["task_success_rate"],
                "task_delta": round(c["task_success_rate"] - b["task_success_rate"], 4),
                "baseline_strict": b["strict_success_rate"],
                "candidate_strict": c["strict_success_rate"],
                "strict_delta": round(c["strict_success_rate"] - b["strict_success_rate"], 4),
                "tool_calls_delta": round(c["tool_calls_mean"] - b["tool_calls_mean"], 2),
                "tokens_delta": round(c["tokens_mean"] - b["tokens_mean"], 1),
                "status": status,
            }
        )

    return {
        "baseline_id": baseline.get("experiment_id"),
        "candidate_id": candidate.get("experiment_id"),
        "suite": baseline.get("suite"),
        "suite_task_delta": round(candidate["suite_task_success"] - baseline["suite_task_success"], 4),
        "suite_strict_delta": round(candidate["suite_strict_success"] - baseline["suite_strict_success"], 4),
        "baseline_task": baseline["suite_task_success"],
        "candidate_task": candidate["suite_task_success"],
        "baseline_strict": baseline["suite_strict_success"],
        "candidate_strict": candidate["suite_strict_success"],
        "improved": buckets["improved"],
        "regressed": buckets["regressed"],
        "stable": buckets["stable"],
        "cases": rows,
    }


def load_summary(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        p = p / "summary.json"
    return json.loads(p.read_text())
