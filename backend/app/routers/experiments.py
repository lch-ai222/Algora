"""Read-only API over persisted experiment artifacts + Version Compare."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app import store
from codeagent_eval.compare import compare_experiments

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
