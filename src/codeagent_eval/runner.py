"""CLI closed loop: run an agent over a suite, grade deterministically, aggregate, persist.

    python -m codeagent_eval.runner --agent v1 --suite datasets/mini_store_suite --repeats 3

Agent kinds:
  v1 / v2      MiniAgent (needs an LLM provider configured in .env)
  reference    apply the known-good fix (upper bound; for the discrimination check)
  none         change nothing (lower bound; for the discrimination check)

Per trial we persist config.json / trajectory.jsonl / patch.diff / grader-results.json under
artifacts/runs/<experiment_id>/<case_id>/rep<k>/, and write summary.json + summary.csv with
mean+variance and pass@k (capability) vs pass^k (reliability).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

from codeagent_eval.agent.loop import AgentConfig, MiniAgent, TrialResult
from codeagent_eval.benchmark import (
    EvalCase,
    apply_reference_fix,
    inject_hidden_tests,
    load_suite,
    materialize_case,
)
from codeagent_eval.failure_taxonomy import FailureAttribution, attribute_failure
from codeagent_eval.graders import combine, grade_constraints, grade_patch, grade_tests
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.models import AgentTask, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

AGENT_KINDS = ("v1", "v2", "reference", "none")


# --------------------------------------------------------------------------- #
# One trial
# --------------------------------------------------------------------------- #
def _agent_config(kind: str) -> AgentConfig:
    return AgentConfig(version=kind, detect_repeated_actions=(kind == "v2"))


def _run_agent_trial(
    task: AgentTask, sandbox: WorktreeSandbox, case: EvalCase, provider, config: AgentConfig
) -> TrialResult:
    agent = MiniAgent(provider, config)
    return agent.run(task, sandbox, case_id=case.case_id)


def _run_config(kind: str, provider) -> dict[str, Any]:
    """Provenance recorded on every trial + experiment: model / provider / temperature / sampling.
    Reference/none are deterministic (no model), so those fields are null."""
    if kind in ("v1", "v2") and provider is not None:
        cfg = _agent_config(kind)
        return {
            "provider": provider.settings.llm_provider,
            "model": provider.resolved_model(cfg.complexity),
            "temperature": cfg.temperature,
            "complexity": cfg.complexity,
            "max_tokens": cfg.max_tokens,
        }
    return {"provider": None, "model": None, "temperature": None, "complexity": None, "max_tokens": None}


def _run_reference_trial(sandbox, suite_dir, clean_repo, case) -> TrialResult:
    restored = apply_reference_fix(sandbox.root, suite_dir, clean_repo, case)
    return TrialResult(
        stop_reason="final",
        steps=1,
        final_message=f"applied reference fix to {restored}",
        patch=sandbox.export_patch(),
        changed_files=sandbox.changed_files(),
        completion_checks={"has_changes": True, "ran_tests": False},
        started_at=utc_now_iso(),
        finished_at=utc_now_iso(),
    )


def run_trial(
    kind: str,
    case: EvalCase,
    suite_dir: Path,
    clean_repo: Path,
    provider,
    build_root: Path,
    out_dir: Path,
    repeat: int,
) -> tuple[GradeResult, TrialResult, FailureAttribution]:
    repo = materialize_case(suite_dir, clean_repo, case, build_root=build_root)
    try:
        with WorktreeSandbox(repo) as sb:
            project_instructions = _read_agents_md(sb.root) if kind == "v2" else None
            task = AgentTask(
                instruction=case.instruction,
                workspace_path=str(sb.root),
                max_steps=case.max_steps,
                timeout_seconds=case.timeout_seconds,
                project_instructions=project_instructions,
            )
            if kind in ("v1", "v2"):
                trial = _run_agent_trial(task, sb, case, provider, _agent_config(kind))
            elif kind == "reference":
                trial = _run_reference_trial(sb, suite_dir, clean_repo, case)
            else:  # none
                trial = TrialResult(stop_reason="final", patch="", started_at=utc_now_iso(),
                                    finished_at=utc_now_iso())

            # Capture the agent's real change BEFORE injecting hidden tests.
            patch, changed_files = trial.patch, trial.changed_files
            inject_hidden_tests(sb.root, suite_dir, case)

            test = grade_tests(sb, case)
            constraint = grade_constraints(case, trial, changed_files, patch)
            patch_grade = grade_patch(patch, changed_files, base_repo=repo)
            grade = combine(case.case_id, test, constraint, patch_grade)
            attribution = attribute_failure(case, trial, grade)

            # Full provenance so the V1/V2 attribution discipline (same model/provider/
            # temperature/budget) is auditable from the artifact alone.
            config_meta = {
                "agent": kind,
                "case_id": case.case_id,
                "task_type": case.task_type,
                **_run_config(kind, provider),
                "max_steps": case.max_steps,       # step budget
                "timeout_seconds": case.timeout_seconds,  # wall-clock budget
                "repeat": repeat,
                "stop_reason": trial.stop_reason,
            }
            _persist_trial(out_dir / case.case_id / f"rep{repeat}", config_meta, trial, grade, attribution)
            return grade, trial, attribution
    finally:
        import shutil

        shutil.rmtree(repo, ignore_errors=True)


def _read_agents_md(root: Path) -> str | None:
    p = root / "AGENTS.md"
    return p.read_text() if p.exists() else None


def _persist_trial(
    trial_dir: Path, config_meta: dict[str, Any], trial: TrialResult, grade: GradeResult,
    attribution: FailureAttribution,
) -> None:
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "config.json").write_text(json.dumps(config_meta, indent=2))
    (trial_dir / "patch.diff").write_text(trial.patch)
    with (trial_dir / "trajectory.jsonl").open("w") as fh:
        for ev in trial.events:
            fh.write(ev.model_dump_json() + "\n")
    (trial_dir / "grader-results.json").write_text(grade.model_dump_json(indent=2))
    (trial_dir / "failure-tags.json").write_text(attribution.model_dump_json(indent=2))


# --------------------------------------------------------------------------- #
# Experiment (cases x repeats) + aggregation
# --------------------------------------------------------------------------- #
def _aggregate_case(
    case_id: str, grades: list[GradeResult], trials: list[TrialResult], attrs: list[FailureAttribution]
) -> dict[str, Any]:
    task = [g.task_success for g in grades]
    strict = [g.strict_success for g in grades]
    tool_calls = [t.tool_call_count for t in trials]
    durations = [t.duration_ms for t in trials]
    tokens = [sum(c.total_tokens for c in t.llm_calls) for t in trials]
    k = len(grades)
    failure_tags: dict[str, int] = {}
    for a in attrs:
        if a.failed and a.primary:
            failure_tags[a.primary] = failure_tags.get(a.primary, 0) + 1
    return {
        "case_id": case_id,
        "repeats": k,
        "task_success_rate": round(sum(task) / k, 4),
        "strict_success_rate": round(sum(strict) / k, 4),
        "pass_at_k": int(any(task)),  # capability: at least one success
        "pass_pow_k": int(all(task)),  # reliability: every run succeeds
        "tool_calls_mean": round(statistics.mean(tool_calls), 2),
        "tool_calls_std": round(statistics.pstdev(tool_calls), 2),
        "duration_ms_mean": round(statistics.mean(durations), 1),
        "tokens_mean": round(statistics.mean(tokens), 1),
        "failure_tags": failure_tags,
    }


def run_experiment(
    kind: str, suite_dir: Path, provider, repeats: int, case_filter: list[str] | None, out_root: Path
) -> dict[str, Any]:
    suite = load_suite(suite_dir)
    clean_repo = suite.repo
    cases = [c for c in suite.cases if not case_filter or c.case_id in case_filter]
    experiment_id = f"{kind}-{utc_now_iso().replace(':', '').replace('-', '')}"
    out_dir = out_root / experiment_id
    build_root = Path(tempfile.mkdtemp(prefix="cae-run-"))

    print(f"Experiment {experiment_id}: {len(cases)} cases x {repeats} repeats (agent={kind})")
    per_case: list[dict[str, Any]] = []
    for case in cases:
        grades, trials, attrs = [], [], []
        for r in range(repeats):
            grade, trial, attribution = run_trial(
                kind, case, suite_dir, clean_repo, provider, build_root, out_dir, r
            )
            grades.append(grade)
            trials.append(trial)
            attrs.append(attribution)
        agg = _aggregate_case(case.case_id, grades, trials, attrs)
        per_case.append(agg)
        print(f"  {case.case_id}: task={agg['task_success_rate']} strict={agg['strict_success_rate']} "
              f"(pass@k={agg['pass_at_k']} pass^k={agg['pass_pow_k']}, tools≈{agg['tool_calls_mean']})")

    import shutil

    shutil.rmtree(build_root, ignore_errors=True)

    summary = {
        "experiment_id": experiment_id,
        "agent": kind,
        "suite": suite.name,
        "repeats": repeats,
        # Run provenance — constant across the experiment, so a V1/V2 comparison is only valid
        # when these match (same model / provider / temperature / sampling).
        "run_config": _run_config(kind, provider),
        "cases": per_case,
        "suite_task_success": round(statistics.mean([c["task_success_rate"] for c in per_case]), 4),
        "suite_strict_success": round(statistics.mean([c["strict_success_rate"] for c in per_case]), 4),
        "created_at": utc_now_iso(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_csv(out_dir / "summary.csv", per_case)
    print(f"\nSuite: task={summary['suite_task_success']} strict={summary['suite_strict_success']}")
    print(f"Artifacts: {out_dir}")
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CodeAgent Eval Lab runner")
    parser.add_argument("--agent", choices=AGENT_KINDS, default="v1")
    parser.add_argument("--suite", default="datasets/mini_store_suite")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="*", help="filter to these case_ids")
    parser.add_argument("--out", default="artifacts/runs")
    args = parser.parse_args(argv)

    provider = None
    if args.agent in ("v1", "v2"):
        from codeagent_eval.llm import LlmProvider
        from codeagent_eval.settings import load_settings

        provider = LlmProvider(load_settings())
        if not provider.enabled:
            print(f"ERROR: agent={args.agent} needs an LLM provider. {provider._availability_error()}",
                  file=sys.stderr)
            return 2

    run_experiment(args.agent, Path(args.suite), provider, args.repeats, args.cases, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
