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


def _write_report_trial(root: Path, exp_id: str, case_id: str, *, task: bool) -> None:
    trial = root / exp_id / case_id / "rep0"
    trial.mkdir(parents=True, exist_ok=True)
    (trial / "config.json").write_text(json.dumps({
        "agent": exp_id.split("-")[0], "case_id": case_id,
        "provider": "test", "model": "controlled-model",
    }))
    (trial / "grader-results.json").write_text(json.dumps({
        "case_id": case_id, "task_success": task, "strict_success": task,
    }))
    (trial / "failure-tags.json").write_text(json.dumps({
        "case_id": case_id, "failed": not task,
        "primary": None if task else "UNKNOWN", "tags": [],
    }))


def _case(cid: str, task: float) -> dict:
    return {"case_id": cid, "repeats": 1, "task_success_rate": task, "strict_success_rate": task,
            "pass_at_k": int(task > 0), "pass_pow_k": int(task >= 1), "tool_calls_mean": 5.0,
            "tool_calls_std": 0.0, "duration_ms_mean": 100.0, "tokens_mean": 50.0, "failure_tags": {}}


@pytest.fixture
def fake_runs(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _write_experiment(root, "v1-X", "v1", 0.5, [_case("a", 1.0), _case("b", 0.0)])
    _write_experiment(root, "v2-X", "v2", 1.0, [_case("a", 1.0), _case("b", 1.0)])
    report_case = "bugfix-cart-merge"
    # One inspectable trial, using a real suite case so it can also feed the report endpoint.
    trial = root / "v1-X" / report_case / "rep0"
    trial.mkdir(parents=True)
    (trial / "config.json").write_text(json.dumps({"agent": "v1", "stop_reason": "final"}))
    (trial / "patch.diff").write_text("diff --git a/x b/x\n+ok\n")
    (trial / "trajectory.jsonl").write_text(
        json.dumps({"event_id": "e1", "step": 1, "type": "tool_call", "name": "read_file",
                    "payload": {}, "created_at": "t"}) + "\n"
    )
    (trial / "grader-results.json").write_text(json.dumps({"case_id": "a", "task_success": True}))
    _write_report_trial(root, "v1-X", report_case, task=False)
    _write_report_trial(root, "v2-X", report_case, task=True)
    _write_experiment(root, "claude_code-X", "claude_code", 1.0, [_case(report_case, 1.0)])
    _write_report_trial(root, "claude_code-X", report_case, task=True)
    monkeypatch.setattr(store, "_runs_root", lambda: root)
    return root


def test_list_and_get_experiment(fake_runs):
    c = TestClient(app)
    exps = c.get("/api/experiments").json()
    assert {e["experiment_id"] for e in exps} == {"v1-X", "v2-X", "claude_code-X"}
    assert next(e for e in exps if e["experiment_id"] == "claude_code-X")["report_ready"] is True
    detail = c.get("/api/experiments/v1-X").json()
    assert detail["suite_task_success"] == 0.5
    assert c.get("/api/experiments/nope").status_code == 404


def test_get_trial(fake_runs):
    c = TestClient(app)
    tr = c.get("/api/experiments/v1-X/cases/bugfix-cart-merge/reps/0").json()
    assert tr["grade"]["task_success"] is False
    assert len(tr["events"]) == 1
    assert "diff --git" in tr["patch"]


def test_compare_endpoint(fake_runs):
    c = TestClient(app)
    cmp = c.get("/api/compare", params={"baseline": "v1-X", "candidate": "v2-X"}).json()
    assert cmp["improved"] == ["b"]
    assert cmp["regressed"] == []
    assert cmp["suite_task_delta"] == 0.5


def test_cross_agent_endpoint_uses_static_report_fact_model(fake_runs):
    c = TestClient(app)
    response = c.get(
        "/api/cross-agent",
        params=[("experiments", "v1-X"), ("experiments", "claude_code-X")],
    )
    report = response.json()

    assert response.status_code == 200, response.text
    assert report["schema"] == "algora.static_report.v1"
    assert report["suite"]["name"] == "mini_store"
    assert [arm["experiment_id"] for arm in report["arms"]] == ["v1-X", "claude_code-X"]
    assert report["comparisons"][0]["task_success"]["available"] is True
    assert report["comparisons"][0]["task_success"]["difference"] == -1.0


def test_cross_agent_rejects_mixed_suites_duplicates_and_unsafe_ids(fake_runs):
    _write_experiment(fake_runs, "v3-long", "v3", 0.0, [])
    summary_path = fake_runs / "v3-long" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["suite"] = "mini_store_long"
    summary_path.write_text(json.dumps(summary))
    c = TestClient(app)

    assert c.get("/api/cross-agent", params=[
        ("experiments", "v1-X"), ("experiments", "v3-long"),
    ]).status_code == 400
    assert c.get("/api/cross-agent", params=[
        ("experiments", "v1-X"), ("experiments", "v1-X"),
    ]).status_code == 400
    assert c.get("/api/cross-agent", params={"experiments": ".."}).status_code == 404
    assert store.get_experiment("../v1-X") is None
