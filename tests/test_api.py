"""M3 backend: the read-only API serves experiments/trials/compare from the artifact tree.

Uses a synthetic artifacts dir (monkeypatched) so it does not depend on real runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import store  # noqa: E402
from backend.app.main import app  # noqa: E402


def _write_experiment(root: Path, exp_id: str, agent: str, task: float, cases: list[dict]) -> None:
    d = root / exp_id
    d.mkdir(parents=True)
    summary = {
        "experiment_id": exp_id, "agent": agent, "suite": "mini_store", "repeats": 1,
        "suite_task_success": task, "suite_strict_success": task,
        "created_at": "2026-07-11T00:00:00Z", "cases": cases,
    }
    (d / "summary.json").write_text(json.dumps(summary))


def _case(cid: str, task: float) -> dict:
    return {"case_id": cid, "repeats": 1, "task_success_rate": task, "strict_success_rate": task,
            "pass_at_k": int(task > 0), "pass_pow_k": int(task >= 1), "tool_calls_mean": 5.0,
            "tool_calls_std": 0.0, "duration_ms_mean": 100.0, "tokens_mean": 50.0, "failure_tags": {}}


@pytest.fixture
def fake_runs(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _write_experiment(root, "v1-X", "v1", 0.5, [_case("a", 1.0), _case("b", 0.0)])
    _write_experiment(root, "v2-X", "v2", 1.0, [_case("a", 1.0), _case("b", 1.0)])
    # one trial for a
    trial = root / "v1-X" / "a" / "rep0"
    trial.mkdir(parents=True)
    (trial / "config.json").write_text(json.dumps({"agent": "v1", "stop_reason": "final"}))
    (trial / "patch.diff").write_text("diff --git a/x b/x\n+ok\n")
    (trial / "trajectory.jsonl").write_text(
        json.dumps({"event_id": "e1", "step": 1, "type": "tool_call", "name": "read_file",
                    "payload": {}, "created_at": "t"}) + "\n"
    )
    (trial / "grader-results.json").write_text(json.dumps({"case_id": "a", "task_success": True}))
    monkeypatch.setattr(store, "_runs_root", lambda: root)
    return root


def test_list_and_get_experiment(fake_runs):
    c = TestClient(app)
    exps = c.get("/api/experiments").json()
    assert {e["experiment_id"] for e in exps} == {"v1-X", "v2-X"}
    detail = c.get("/api/experiments/v1-X").json()
    assert detail["suite_task_success"] == 0.5
    assert c.get("/api/experiments/nope").status_code == 404


def test_get_trial(fake_runs):
    c = TestClient(app)
    tr = c.get("/api/experiments/v1-X/cases/a/reps/0").json()
    assert tr["grade"]["task_success"] is True
    assert len(tr["events"]) == 1
    assert "diff --git" in tr["patch"]


def test_compare_endpoint(fake_runs):
    c = TestClient(app)
    cmp = c.get("/api/compare", params={"baseline": "v1-X", "candidate": "v2-X"}).json()
    assert cmp["improved"] == ["b"]
    assert cmp["regressed"] == []
    assert cmp["suite_task_delta"] == 0.5
