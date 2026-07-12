"""Read experiment artifacts off disk for the API.

The runner already persists everything under artifacts/runs/<experiment_id>/ (summary.json +
per-trial config/patch/trajectory/grader/failure-tags). The console is a thin read-only view
over those files — no separate database for the MVP (SQLite is the documented upgrade).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_AGENT_PREFIXES = ("v1-", "v2-", "reference-", "none-")


def _runs_root() -> Path:
    # Resolve relative to the repo root (two levels up from backend/app).
    return Path(__file__).resolve().parents[2] / "artifacts" / "runs"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def list_experiments() -> list[dict[str, Any]]:
    root = _runs_root()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in root.iterdir():
        if not d.is_dir() or not d.name.startswith(_AGENT_PREFIXES):
            continue
        summary = _read_json(d / "summary.json")
        if not summary:
            continue
        out.append(
            {
                "experiment_id": summary.get("experiment_id", d.name),
                "agent": summary.get("agent"),
                "suite": summary.get("suite"),
                "repeats": summary.get("repeats"),
                "suite_task_success": summary.get("suite_task_success"),
                "suite_strict_success": summary.get("suite_strict_success"),
                "created_at": summary.get("created_at"),
                "num_cases": len(summary.get("cases", [])),
            }
        )
    out.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return out


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    return _read_json(_runs_root() / experiment_id / "summary.json")


def get_trial(experiment_id: str, case_id: str, rep: int) -> dict[str, Any] | None:
    trial_dir = _runs_root() / experiment_id / case_id / f"rep{rep}"
    if not trial_dir.is_dir():
        return None
    events: list[dict[str, Any]] = []
    traj = trial_dir / "trajectory.jsonl"
    if traj.exists():
        for line in traj.read_text().splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    patch_path = trial_dir / "patch.diff"
    return {
        "experiment_id": experiment_id,
        "case_id": case_id,
        "rep": rep,
        "config": _read_json(trial_dir / "config.json"),
        "grade": _read_json(trial_dir / "grader-results.json"),
        "failure": _read_json(trial_dir / "failure-tags.json"),
        "patch": patch_path.read_text() if patch_path.exists() else "",
        "events": events,
    }


def list_trial_reps(experiment_id: str, case_id: str) -> list[int]:
    case_dir = _runs_root() / experiment_id / case_id
    if not case_dir.is_dir():
        return []
    reps = []
    for d in case_dir.iterdir():
        if d.is_dir() and d.name.startswith("rep"):
            try:
                reps.append(int(d.name[3:]))
            except ValueError:
                continue
    return sorted(reps)
