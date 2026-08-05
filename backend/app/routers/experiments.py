"""Read-only API over persisted experiment artifacts + Version Compare."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app import store
from codeagent_eval.compare import compare_experiments
from codeagent_eval.report import ReportError, build_report_data

router = APIRouter(prefix="/api", tags=["experiments"])


@router.get("/experiments")
def list_experiments():
    return store.list_experiments()


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    summary = store.get_experiment(experiment_id)
    if summary is None:
        raise HTTPException(404, f"no such experiment: {experiment_id}")
    return summary


@router.get("/experiments/{experiment_id}/cases/{case_id}/reps")
def list_reps(experiment_id: str, case_id: str):
    return store.list_trial_reps(experiment_id, case_id)


@router.get("/experiments/{experiment_id}/cases/{case_id}/reps/{rep}")
def get_trial(experiment_id: str, case_id: str, rep: int):
    trial = store.get_trial(experiment_id, case_id, rep)
    if trial is None:
        raise HTTPException(404, f"no such trial: {experiment_id}/{case_id}/rep{rep}")
    return trial


@router.get("/compare")
def compare(baseline: str, candidate: str):
    b = store.get_experiment(baseline)
    c = store.get_experiment(candidate)
    if b is None or c is None:
        raise HTTPException(404, "baseline or candidate experiment not found")
    return compare_experiments(b, c)


@router.get("/cross-agent")
def cross_agent_report(experiments: list[str] = Query(...)):
    """Build the W3-5 fact model in memory from selected, persisted experiments."""
    if not 1 <= len(experiments) <= 6:
        raise HTTPException(400, "select between 1 and 6 experiments")
    if len(set(experiments)) != len(experiments):
        raise HTTPException(400, "experiment selection contains duplicates")

    summaries = [store.get_experiment(experiment_id) for experiment_id in experiments]
    if any(summary is None for summary in summaries):
        raise HTTPException(404, "one or more experiments were not found")
    suite_names = {summary.get("suite") for summary in summaries if summary is not None}
    if len(suite_names) != 1 or None in suite_names:
        raise HTTPException(400, "cross-agent experiments must use the same declared suite")
    suite_dir = store.find_suite(str(next(iter(suite_names))))
    if suite_dir is None:
        raise HTTPException(400, "the experiment suite is unavailable or ambiguous")
    paths = [store.get_experiment_path(experiment_id) for experiment_id in experiments]
    if any(path is None for path in paths):
        raise HTTPException(404, "one or more experiment artifact directories were not found")
    try:
        return build_report_data(
            [path for path in paths if path is not None],
            suite_dir,
            labels=experiments,
        )
    except (ReportError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
