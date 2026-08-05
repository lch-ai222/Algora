"""W3-5a: static reports consume artifacts honestly and render without a service."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeagent_eval.report import ReportError, build_report_data, write_static_report

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "datasets" / "mini_store_suite"
CASES = ("bugfix-cart-merge", "spec-catalog-search")


def write_trial(
    experiment: Path, case_id: str, repeat: int, *, task: bool, strict: bool,
    cost: float | None, cost_source: str = "derived", infra: bool = False,
    legacy_agent_result: bool = False,
) -> None:
    trial_dir = experiment / case_id / f"rep{repeat}"
    trial_dir.mkdir(parents=True)
    (trial_dir / "config.json").write_text(json.dumps({
        "agent": "v3", "case_id": case_id, "task_type": "bugfix",
        "provider": "deepseek", "model": "deepseek-v4-flash",
    }))
    (trial_dir / "grader-results.json").write_text(json.dumps({
        "case_id": case_id, "task_success": task, "strict_success": strict,
    }))
    (trial_dir / "failure-tags.json").write_text(json.dumps({
        "case_id": case_id, "failed": not task,
        "primary": "ENVIRONMENT" if infra else ("UNKNOWN" if not task else None), "tags": [],
    }))
    payload = {
        "cost_usd": cost, "cost_source": cost_source,
        "prompt_tokens": 100, "completion_tokens": 20, "duration_ms": 1000,
        "completion_checks": {"provider_error": infra},
    }
    name = "agent-result.json" if legacy_agent_result else "trial.json"
    (trial_dir / name).write_text(json.dumps(payload))


def write_experiment(root: Path, experiment_id: str, trials: list[dict],
                     *, suite: str = "mini_store") -> Path:
    experiment = root / experiment_id
    experiment.mkdir(parents=True)
    (experiment / "summary.json").write_text(json.dumps({
        "experiment_id": experiment_id, "agent": "v3", "adapter": "mini_agent",
        "harness": "v3", "suite": suite,
        "run_config": {
            "adapter": "mini_agent", "adapter_version": "test+v3", "harness": "v3",
            "provider": "deepseek", "model": "deepseek-v4-flash",
            "max_wall_clock_override": 120, "max_steps_override": 8, "ablate": [],
        },
    }))
    for spec in trials:
        write_trial(experiment, **spec)
    return experiment


def paired_fixture(tmp_path: Path) -> tuple[Path, Path]:
    a_specs = [
        {"case_id": case_id, "repeat": repeat, "task": True, "strict": repeat == 0,
         "cost": 0.1 + repeat * 0.02}
        for case_id in CASES for repeat in range(2)
    ]
    b_specs = [
        {"case_id": case_id, "repeat": repeat,
         "task": not (case_id == CASES[1] and repeat == 1), "strict": False,
         "cost": None if (case_id == CASES[1] and repeat == 1) else 0.2 + repeat * 0.02}
        for case_id in CASES for repeat in range(2)
    ]
    return (
        write_experiment(tmp_path, "arm-a", a_specs),
        write_experiment(tmp_path, "arm-b", b_specs),
    )


def test_report_has_case_macro_strata_paired_tests_and_honest_cost(tmp_path: Path):
    a, b = paired_fixture(tmp_path)
    report = build_report_data([a, b], SUITE, labels=["A", "B"], resamples=200)

    assert report["schema"] == "algora.static_report.v1"
    assert report["suite"]["cases"] == list(CASES)
    assert report["arms"][0]["task_success"]["point"] == 1.0
    assert report["arms"][0]["cost"]["cost_per_success_usd"] == pytest.approx(0.11)
    assert report["arms"][1]["cost"]["total_cost_usd"] is None
    assert report["arms"][1]["cost"]["cost_per_success_usd"] is None
    assert report["arms"][1]["cost"]["reason"] == "cost available for 3/4 valid trials"
    assert report["arms"][0]["strata"]["task_type"]
    assert report["comparisons"][0]["task_success"]["available"] is True
    assert report["comparisons"][0]["cost"]["available"] is False


def test_infra_invalid_is_excluded_from_every_denominator(tmp_path: Path):
    experiment = write_experiment(tmp_path, "infra", [
        {"case_id": CASES[0], "repeat": 0, "task": True, "strict": True, "cost": 0.1},
        {"case_id": CASES[1], "repeat": 0, "task": False, "strict": False,
         "cost": None, "infra": True, "legacy_agent_result": True},
    ])
    report = build_report_data([experiment], SUITE, resamples=50)
    arm = report["arms"][0]

    assert arm["trials"] == {"total": 2, "valid": 1, "infra_invalid": 1}
    assert arm["task_success"]["point"] == 1.0
    assert arm["cost"]["n_trials"] == arm["cost"]["n_priced"] == 1
    assert report["suite"]["cases"] == list(CASES), "scheduled infra-only cases stay visible"
    assert CASES[1] not in arm["case_rates"]


def test_legacy_zero_derived_cost_is_unavailable_not_free(tmp_path: Path):
    experiment = write_experiment(tmp_path, "legacy", [{
        "case_id": CASES[0], "repeat": 0, "task": True, "strict": True,
        "cost": 0.0, "legacy_agent_result": True,
    }])
    report = build_report_data([experiment], SUITE, resamples=50)
    cost = report["arms"][0]["cost"]

    assert cost["n_priced"] == 0
    assert cost["total_cost_usd"] is None
    assert cost["cost_per_success_usd"] is None


def test_static_outputs_are_offline_escaped_and_share_one_fact_source(tmp_path: Path):
    a, b = paired_fixture(tmp_path)
    report = build_report_data([a, b], SUITE, labels=["<A>", "B|arm"], resamples=50)
    destination = write_static_report(report, tmp_path / "report", title="<Algora & report>")

    saved = json.loads((destination / "report.json").read_text())
    markdown = (destination / "report.md").read_text()
    page = (destination / "report.html").read_text()
    assert saved["arms"][0]["label"] == "<A>"
    assert "B\\|arm" in markdown
    assert "&lt;Algora &amp; report&gt;" in page and "&lt;A&gt;" in page
    assert "Evidence warnings" in markdown and "indicative only" in page
    assert "<script" not in page and "https://" not in page and "http://" not in page
    assert {path.name for path in destination.iterdir()} == {"report.json", "report.md", "report.html"}


def test_complete_paired_cost_renders_a_cluster_interval(tmp_path: Path):
    a, b = paired_fixture(tmp_path)
    trial_file = b / CASES[1] / "rep1" / "trial.json"
    payload = json.loads(trial_file.read_text())
    payload["cost_usd"] = 0.24
    trial_file.write_text(json.dumps(payload))
    report = build_report_data([a, b], SUITE, labels=["A", "B"], resamples=100)
    destination = write_static_report(report, tmp_path / "report")
    comparison = report["comparisons"][0]["cost"]

    assert comparison["available"] is True
    assert comparison["case_macro_delta_low_usd"] is not None
    assert "Case-macro cost delta" in (destination / "report.md").read_text()
    assert "indicative only" in (destination / "report.html").read_text()


def test_report_output_never_overwrites(tmp_path: Path):
    a, _ = paired_fixture(tmp_path)
    report = build_report_data([a], SUITE, resamples=20)
    destination = write_static_report(report, tmp_path / "report")

    with pytest.raises(ReportError, match="refusing to overwrite"):
        write_static_report(report, destination)


def test_invalid_suite_labels_and_case_ids_are_refused(tmp_path: Path):
    experiment = write_experiment(tmp_path, "wrong-suite", [{
        "case_id": CASES[0], "repeat": 0, "task": True, "strict": True, "cost": 0.1,
    }], suite="another-suite")
    with pytest.raises(ReportError, match="reports suite"):
        build_report_data([experiment], SUITE)
    with pytest.raises(ReportError, match="labels"):
        build_report_data([experiment], SUITE, labels=[])


def test_cli_is_directly_executable_from_the_checkout():
    result = subprocess.run(
        [sys.executable, "scripts/build_static_report.py", "--help"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--suite" in result.stdout and "--out" in result.stdout
