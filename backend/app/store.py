"""Read experiment artifacts off disk for the API.

The runner already persists everything under artifacts/runs/<experiment_id>/ (summary.json +
per-trial config/patch/trajectory/grader/failure-tags). The console is a thin read-only view
over those files. A separate database is unnecessary while artifacts remain the authoritative,
immutable fact source; an indexed store is an optional scale upgrade, not a second truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from codeagent_eval.report import ReportError, load_experiment

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _runs_root() -> Path:
    # Resolve relative to the repo root (two levels up from backend/app).
    return Path(__file__).resolve().parents[2] / "artifacts" / "runs"


def _datasets_root() -> Path:
    return Path(__file__).resolve().parents[2] / "datasets"


def _artifact_dir(root: Path, artifact_id: str) -> Path | None:
    """Resolve one direct child without allowing traversal through user input."""
    if not _ARTIFACT_ID.fullmatch(artifact_id) or artifact_id in {".", ".."}:
        return None
    candidate = root / artifact_id
    try:
        if candidate.is_symlink() or candidate.resolve().parent != root.resolve():
            return None
    except OSError:
        return None
    return candidate


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
        if not d.is_dir() or _artifact_dir(root, d.name) is None:
            continue
        summary = _read_json(d / "summary.json")
        if not summary:
            continue
        experiment_id = summary.get("experiment_id") or d.name
        if experiment_id != d.name:
            continue
        run_config = summary.get("run_config") or {}
        suite_dir = find_suite(str(summary.get("suite")))
        report_ready = False
        if suite_dir is not None:
            try:
                report_ready = bool(load_experiment(d, suite_dir).valid_records)
            except (ReportError, ValueError):
                pass
        out.append(
            {
                "experiment_id": experiment_id,
                "agent": summary.get("agent"),
                "adapter": summary.get("adapter") or run_config.get("adapter"),
                "harness": summary.get("harness") or run_config.get("harness"),
                "provider": run_config.get("provider"),
                "model": run_config.get("model"),
                "suite": summary.get("suite"),
                "repeats": summary.get("repeats"),
                "suite_task_success": summary.get("suite_task_success"),
                "suite_strict_success": summary.get("suite_strict_success"),
                "created_at": summary.get("created_at"),
                "num_cases": len(summary.get("cases", [])),
                "report_ready": report_ready,
            }
        )
    out.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return out


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    experiment = _artifact_dir(_runs_root(), experiment_id)
    if experiment is None:
        return None
    summary = _read_json(experiment / "summary.json")
    if summary and summary.get("experiment_id", experiment_id) != experiment_id:
        return None
    return summary


def get_experiment_path(experiment_id: str) -> Path | None:
    experiment = _artifact_dir(_runs_root(), experiment_id)
    if experiment is None or get_experiment(experiment_id) is None:
        return None
    return experiment


def find_suite(suite_name: str) -> Path | None:
    """Find a committed suite by its declared name, not by a caller-supplied path."""
    root = _datasets_root()
    if not root.is_dir():
        return None
    matches = []
    for suite_file in root.glob("*/suite.json"):
        payload = _read_json(suite_file)
        if payload and payload.get("name") == suite_name:
            matches.append(suite_file.parent)
    return matches[0] if len(matches) == 1 else None


def get_trial(experiment_id: str, case_id: str, rep: int) -> dict[str, Any] | None:
    experiment = get_experiment_path(experiment_id)
    case = _artifact_dir(experiment, case_id) if experiment is not None else None
    if case is None or rep < 0:
        return None
    trial_dir = _artifact_dir(case, f"rep{rep}")
    if trial_dir is None:
        return None
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
    experiment = get_experiment_path(experiment_id)
    case_dir = _artifact_dir(experiment, case_id) if experiment is not None else None
    if case_dir is None:
        return []
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
