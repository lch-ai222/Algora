"""W1-6: parallel execution and trial-level resume must not change what an experiment means.

The whole point of the runner is that a number is attributable to a configuration. Parallelism
and resume both open ways for that to quietly stop being true — trials colliding in a shared
build directory, aggregation following completion order, a resumed run blending two
configurations, a half-written trial being adopted as finished. These tests pin each one.

The deterministic ``reference``/``none`` tiers are used throughout: no provider, no network,
and a known-correct answer, so any difference observed is the scheduler's doing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeagent_eval.runner import (
    TrialSpec,
    execute_trial,
    harness_failure,
    load_completed_trial,
    run_experiment,
    trial_dir,
)

SUITE = Path("datasets/mini_store_suite")
CASES = ["bugfix-pricing-tax", "bugfix-cart-merge", "spec-catalog-search"]

# Fields that legitimately differ between two runs of the same configuration.
VOLATILE = {"experiment_id", "created_at", "workers", "resumed_trials"}
TIMING = {"duration_ms_mean"}


def comparable(summary: dict) -> dict:
    """The part of a summary that must be reproducible across schedulers."""
    trimmed = {k: v for k, v in summary.items() if k not in VOLATILE}
    trimmed["cases"] = [
        {k: v for k, v in case.items() if k not in TIMING} for case in trimmed["cases"]
    ]
    return trimmed


def run(out: Path, *, workers: int = 1, cases=None, repeats: int = 1, resume=None, kind="reference"):
    return run_experiment(
        kind,
        SUITE,
        None,
        repeats,
        cases if cases is not None else CASES,
        out,
        workers=workers,
        resume_experiment_id=resume,
    )


def test_automatic_experiment_ids_are_unique_within_the_same_second(monkeypatch):
    """Independent runner processes must never share an artifact or cleanup directory."""
    from codeagent_eval import runner

    monkeypatch.setattr(runner, "utc_now_iso", lambda: "2026-08-04T12:20:05Z")

    first = runner._new_experiment_id("reference")
    second = runner._new_experiment_id("reference")

    assert first.startswith("reference-20260804T122005Z-")
    assert second.startswith("reference-20260804T122005Z-")
    assert first != second


# --------------------------------------------------------------------------- #
# Parallelism must be a scheduling detail, not a semantic one
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_parallel_and_serial_summaries_are_identical(tmp_path):
    serial = run(tmp_path / "serial", workers=1, repeats=2)
    parallel = run(tmp_path / "parallel", workers=4, repeats=2)

    assert comparable(serial) == comparable(parallel)
    assert serial["workers"] == 1 and parallel["workers"] == 4


@pytest.mark.slow
def test_aggregation_follows_suite_order_not_completion_order(tmp_path):
    """Cases finish in whatever order the pool returns them; the report must not reflect that."""
    parallel = run(tmp_path / "parallel", workers=4)

    assert [c["case_id"] for c in parallel["cases"]] == CASES


@pytest.mark.slow
def test_repeats_of_one_case_do_not_collide_in_the_build_directory(tmp_path):
    """Every trial materializes its own repo. Sharing one path per case — which is what the
    serial runner could get away with — would make concurrent repeats overwrite each other."""
    summary = run(tmp_path / "out", workers=4, cases=[CASES[0]], repeats=4)

    assert summary["total_trials"] == 4
    assert summary["valid_trials"] == 4
    assert summary["infra_failures"] == 0
    assert summary["cases"][0]["task_success_rate"] == 1.0


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_resume_reuses_finished_trials_and_reproduces_the_summary(tmp_path):
    first = run(tmp_path / "out")
    resumed = run(tmp_path / "out", resume=first["experiment_id"])

    assert resumed["resumed_trials"] == len(CASES)
    assert comparable(first) == comparable(resumed)


@pytest.mark.slow
def test_resume_reruns_only_the_incomplete_trial(tmp_path):
    first = run(tmp_path / "out")
    out_dir = tmp_path / "out" / first["experiment_id"]
    (trial_dir(out_dir, CASES[1], 0) / "trial-complete.json").unlink()

    resumed = run(tmp_path / "out", resume=first["experiment_id"])

    assert resumed["resumed_trials"] == len(CASES) - 1
    assert comparable(first) == comparable(resumed)


@pytest.mark.slow
def test_resume_refuses_a_different_configuration(tmp_path):
    """Blending two configurations into one summary is a provenance failure that nothing
    downstream could detect, so it has to fail here."""
    first = run(tmp_path / "out")

    with pytest.raises(ValueError, match="configuration differs"):
        run(tmp_path / "out", cases=CASES[:2], resume=first["experiment_id"])
    with pytest.raises(ValueError, match="configuration differs"):
        run(tmp_path / "out", kind="none", resume=first["experiment_id"])


def test_resume_requires_an_existing_manifest(tmp_path):
    with pytest.raises(ValueError, match="no manifest.json"):
        run(tmp_path / "out", resume="never-ran")


# --------------------------------------------------------------------------- #
# Checkpoint integrity
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_a_finished_trial_round_trips_including_trajectory_metrics(tmp_path):
    """Resume must recover the trajectory-derived metrics, not only the score — otherwise a
    resumed experiment silently reports different tool-call and test-run aggregates."""
    summary = run(tmp_path / "out")
    out_dir = tmp_path / "out" / summary["experiment_id"]

    loaded = load_completed_trial(trial_dir(out_dir, CASES[0], 0))
    assert loaded is not None
    grade, trial, attribution = loaded
    assert grade.task_success is True
    assert attribution.failed is False
    assert trial.stop_reason == "final"
    assert trial.events, "events must come back from trajectory.jsonl"
    assert trial.completion_checks["ran_tests"] is True


@pytest.mark.slow
@pytest.mark.parametrize(
    "removed", ["trial-complete.json", "trial.json", "grader-results.json", "failure-tags.json"]
)
def test_a_partially_written_trial_is_never_adopted(tmp_path, removed):
    summary = run(tmp_path / "out")
    out_dir = tmp_path / "out" / summary["experiment_id"]
    target = trial_dir(out_dir, CASES[0], 0)
    (target / removed).unlink()

    assert load_completed_trial(target) is None


@pytest.mark.slow
def test_resume_reruns_infra_invalid_trials_instead_of_adopting_them(tmp_path):
    """Found while running the GLM ladder: a provider rate limit marks trials infra-invalid,
    and those directories are complete on disk. Adopting them would freeze a transient outage
    into the experiment's results, so resume must treat them as work still to do."""
    summary = run(tmp_path / "out", cases=[CASES[0]])
    out_dir = tmp_path / "out" / summary["experiment_id"]
    target = trial_dir(out_dir, CASES[0], 0)

    payload = json.loads((target / "trial.json").read_text())
    payload["canonical_stop_reason"] = "error"
    payload["completion_checks"]["provider_error"] = True
    (target / "trial.json").write_text(json.dumps(payload))

    assert load_completed_trial(target) is None

    resumed = run(tmp_path / "out", cases=[CASES[0]], resume=summary["experiment_id"])
    assert resumed["resumed_trials"] == 0, "the rate-limited trial must be attempted again"
    assert resumed["infra_failures"] == 0, "and it succeeds once the provider recovers"


@pytest.mark.slow
def test_an_unknown_schema_version_forces_a_rerun(tmp_path):
    summary = run(tmp_path / "out")
    out_dir = tmp_path / "out" / summary["experiment_id"]
    target = trial_dir(out_dir, CASES[0], 0)
    (target / "trial-complete.json").write_text(json.dumps({"schema_version": 999}))

    assert load_completed_trial(target) is None


# --------------------------------------------------------------------------- #
# A crashed trial is missing evidence, not a failed agent
# --------------------------------------------------------------------------- #
def _spec(case_id: str, tmp_path: Path) -> TrialSpec:
    return TrialSpec(
        kind="reference",
        case_id=case_id,
        suite_dir=str(SUITE),
        out_dir=str(tmp_path),
        build_root=str(tmp_path / "build"),
        repeat=0,
    )


def test_harness_failure_produces_valid_infra_invalid_artifacts(tmp_path):
    from codeagent_eval.benchmark import load_suite
    from codeagent_eval.runner import _is_infra_invalid

    case = load_suite(SUITE).cases[0]
    grade, trial, attribution = harness_failure(
        case, _spec(case.case_id, tmp_path), RuntimeError("disk exploded")
    )

    assert grade.task_success is False and grade.strict_success is False
    assert _is_infra_invalid(trial) is True
    assert attribution.primary == "ENVIRONMENT"
    assert "disk exploded" in trial.completion_checks["harness_error"]
    # Must serialize like any other trial so the console and compare tooling keep working.
    assert json.loads(grade.model_dump_json())["case_id"] == case.case_id
    assert json.loads(trial.model_dump_json())["canonical_stop_reason"] == "error"


def test_a_crashing_trial_is_recorded_instead_of_killing_the_run(tmp_path):
    """One bad trial out of hundreds must not discard the completed ones, so execute_trial
    absorbs its own failures — including one raised before the case could even be resolved."""
    outcome = execute_trial(_spec("does-not-exist", tmp_path))

    assert outcome.case_id == "does-not-exist"
    assert outcome.trial.canonical_stop_reason == "error"
    assert outcome.grade.task_success is False
    # Recorded on disk like any other trial, so the failure is inspectable afterwards.
    assert (trial_dir(tmp_path, "does-not-exist", 0) / "trial-complete.json").is_file()


@pytest.mark.slow
def test_infra_failures_are_excluded_from_the_denominator_and_flagged(tmp_path):
    from codeagent_eval.benchmark import load_suite
    from codeagent_eval.runner import _aggregate_case, _experiment_exit_code

    summary = run(tmp_path / "out", cases=[CASES[0]])
    out_dir = tmp_path / "out" / summary["experiment_id"]
    grade, trial, attribution = load_completed_trial(trial_dir(out_dir, CASES[0], 0))
    case = next(c for c in load_suite(SUITE).cases if c.case_id == CASES[0])
    _, crashed, crashed_attr = harness_failure(
        case, _spec(CASES[0], tmp_path), RuntimeError("boom")
    )

    agg = _aggregate_case(
        CASES[0], [grade, grade], [trial, crashed], [attribution, crashed_attr]
    )

    assert agg["repeats"] == 2
    assert agg["valid_trials"] == 1
    assert agg["infra_failures"] == 1
    assert agg["task_success_rate"] == 1.0  # the crash is not scored as a failure
    assert _experiment_exit_code({"infra_failures": 1}) == 3


# --------------------------------------------------------------------------- #
# Step budget as an experimental variable
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_max_steps_override_replaces_the_case_budget_and_is_recorded(tmp_path):
    """A suite every model saturates still discriminates once the budget is tight enough, so
    the step budget has to be settable per experiment and visible in provenance afterwards."""
    summary = run_experiment(
        "reference", SUITE, None, 1, CASES[:1], tmp_path / "out", max_steps_override=3
    )
    config = json.loads(
        (tmp_path / "out" / summary["experiment_id"] / CASES[0] / "rep0" / "config.json").read_text()
    )

    assert config["max_steps"] == 3
    assert config["case_max_steps"] == 20, "the case's own default stays visible for contrast"
    assert summary["run_config"]["max_steps_override"] == 3


@pytest.mark.slow
def test_runs_at_different_budgets_are_different_experiments(tmp_path):
    """Two budgets are two experiments. Resuming across them would average trials that were
    never comparable, which is exactly what the manifest fingerprint exists to prevent."""
    first = run_experiment(
        "reference", SUITE, None, 1, CASES[:1], tmp_path / "out", max_steps_override=8
    )

    with pytest.raises(ValueError, match="configuration differs"):
        run_experiment(
            "reference", SUITE, None, 1, CASES[:1], tmp_path / "out",
            max_steps_override=4, resume_experiment_id=first["experiment_id"],
        )
