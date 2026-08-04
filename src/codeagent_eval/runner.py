"""CLI closed loop: run an agent over a suite, grade deterministically, aggregate, persist.

    python -m codeagent_eval.runner --agent v1 --suite datasets/mini_store_suite --repeats 3
    python -m codeagent_eval.runner --adapter mini_agent --harness v2 --suite datasets/mini_store_suite

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
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

from codeagent_eval import __version__
from codeagent_eval.adapters import (
    ADAPTER_NAMES,
    EXTERNAL_ADAPTERS,
    AgentRunResult,
    BudgetContract,
    ClaudeCodeConfig,
    create_adapter,
)
from codeagent_eval.agent.loop import AgentConfig, TrialResult
from codeagent_eval.benchmark import (
    EvalCase,
    apply_reference_fix,
    inject_hidden_tests,
    load_suite,
    materialize_case,
)
from codeagent_eval.failure_taxonomy import (
    FailureAttribution,
    attribute_failure,
    canonical_stop_reason,
)
from codeagent_eval.graders import combine, grade_constraints, grade_patch, grade_tests
from codeagent_eval.graders.pytest_run import run_pytest
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.models import AgentTask, TraceEvent, TraceEventType, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

AGENT_KINDS = ("v1", "v2", "reference", "none")


# --------------------------------------------------------------------------- #
# One trial
# --------------------------------------------------------------------------- #
def _agent_config(kind: str) -> AgentConfig:
    return AgentConfig(version=kind, detect_repeated_actions=(kind == "v2"))


def _run_adapter_trial(
    task: AgentTask,
    sandbox: WorktreeSandbox,
    case: EvalCase,
    provider,
    *,
    adapter_name: str = "mini_agent",
    max_completion_tokens: int = 2048,
    adapter_config=None,
) -> tuple[TrialResult, AgentRunResult]:
    adapter = create_adapter(
        adapter_name,
        provider=provider,
        harness=task_harness(task),
        max_completion_tokens=max_completion_tokens,
        config=adapter_config,
    )
    probe = adapter.probe()
    if not probe.available:
        raise RuntimeError(probe.detail or f"adapter {adapter_name} is unavailable")
    budget = BudgetContract(
        max_wall_clock_s=case.timeout_seconds,
        max_steps=case.max_steps,
    )
    adapter.prepare(sandbox.root, task, budget, runtime=sandbox)
    try:
        result = adapter.run(task.instruction)
        return result.to_trial_result(), result
    finally:
        adapter.cleanup()


def task_harness(task: AgentTask) -> str:
    """Harness identity is explicit task provenance, never inferred from prompt text."""
    return task.harness_version or "v2"


def _resolve_agent_kind(agent: str | None, adapter: str | None, harness: str) -> str:
    """The agent label used for artifacts and aggregation.

    ``mini_agent`` folds into the V1/V2 harness axis (the harness *is* the system under test);
    an external adapter is its own system, so its name becomes the label directly.
    """
    if adapter and agent:
        raise ValueError("--adapter and legacy --agent are mutually exclusive")
    if adapter in EXTERNAL_ADAPTERS:
        return adapter
    return harness if adapter else (agent or "v1")


def _run_config(
    kind: str,
    provider,
    max_completion_tokens: int = 2048,
    *,
    adapter_config=None,
    adapter_result: AgentRunResult | None = None,
) -> dict[str, Any]:
    """Provenance recorded on every trial + experiment: model / provider / temperature / sampling.
    Reference/none are deterministic (no model), so those fields are null."""
    if kind in EXTERNAL_ADAPTERS:
        manifest = adapter_result.env_manifest if adapter_result else {}
        return {
            "adapter": kind,
            "adapter_version": adapter_result.adapter_version if adapter_result else None,
            "harness": None,
            # An external framework owns its own model client; the OpenAI-compatible provider
            # used by V1/V2 is not in the loop, and saying otherwise would make a cross-agent
            # comparison look controlled when it is not.
            "provider": "external_cli",
            "model": manifest.get("model_reported") or getattr(adapter_config, "model", None),
            "temperature": None,
            "complexity": None,
            "max_tokens": None,
        }
    if kind in ("v1", "v2") and provider is not None:
        cfg = _agent_config(kind)
        return {
            "adapter": "mini_agent",
            "adapter_version": f"{__version__}+{kind}",
            "harness": kind,
            "provider": provider.settings.llm_provider,
            "model": provider.resolved_model(cfg.complexity),
            "temperature": cfg.temperature,
            "complexity": cfg.complexity,
            "max_tokens": max_completion_tokens,
        }
    return {
        "adapter": f"builtin_{kind}",
        "adapter_version": __version__,
        "harness": None,
        "provider": None,
        "model": None,
        "temperature": None,
        "complexity": None,
        "max_tokens": None,
    }


def _run_reference_trial(sandbox, suite_dir, clean_repo, case) -> TrialResult:
    restored = apply_reference_fix(sandbox.root, suite_dir, clean_repo, case)
    preflight = run_pytest(sandbox, [*case.visible_tests, *case.regression_tests])
    return TrialResult(
        stop_reason="final",
        steps=1,
        final_message=f"applied reference fix to {restored}",
        patch=sandbox.export_patch(),
        changed_files=sandbox.changed_files(),
        events=[
            TraceEvent(
                step=1,
                type=TraceEventType.TEST_RESULT,
                name="reference preflight: visible + regression",
                payload={
                    "exit_code": preflight.exit_code,
                    "passed": preflight.passed,
                    "failed": preflight.failed,
                    "errors": preflight.errors,
                },
            )
        ],
        completion_checks={
            "has_changes": True,
            "ran_tests": True,
            "last_test_passed": preflight.all_passed,
        },
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
    max_completion_tokens: int = 2048,
    adapter_config=None,
) -> tuple[GradeResult, TrialResult, FailureAttribution]:
    repo = materialize_case(suite_dir, clean_repo, case, build_root=build_root)
    try:
        with WorktreeSandbox(repo) as sb:
            project_instructions = _read_agents_md(sb.root) if kind == "v2" else None
            task = AgentTask(
                instruction=case.render_instruction(),
                workspace_path=str(sb.root),
                case_id=case.case_id,
                max_steps=case.max_steps,
                timeout_seconds=case.timeout_seconds,
                project_instructions=project_instructions,
                harness_version=kind if kind in ("v1", "v2") else None,
                require_tests_run_before_finish=case.constraints.require_tests_run_before_finish,
            )
            adapter_result: AgentRunResult | None = None
            if kind in ("v1", "v2"):
                trial, adapter_result = _run_adapter_trial(
                    task,
                    sb,
                    case,
                    provider,
                    max_completion_tokens=max_completion_tokens,
                )
            elif kind in EXTERNAL_ADAPTERS:
                trial, adapter_result = _run_adapter_trial(
                    task,
                    sb,
                    case,
                    None,
                    adapter_name=kind,
                    adapter_config=adapter_config,
                )
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
                **_run_config(
                    kind,
                    provider,
                    max_completion_tokens,
                    adapter_config=adapter_config,
                    adapter_result=adapter_result,
                ),
                "max_steps": case.max_steps,       # step budget
                "timeout_seconds": case.timeout_seconds,  # wall-clock budget
                "repeat": repeat,
                "stop_reason": trial.stop_reason,
                "canonical_stop_reason": adapter_result.stop_reason if adapter_result else trial.stop_reason,
            }
            _persist_trial(
                out_dir / case.case_id / f"rep{repeat}",
                config_meta,
                trial,
                grade,
                attribution,
                adapter_result=adapter_result,
            )
            return grade, trial, attribution
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _read_agents_md(root: Path) -> str | None:
    p = root / "AGENTS.md"
    return p.read_text() if p.exists() else None


def _persist_trial(
    trial_dir: Path, config_meta: dict[str, Any], trial: TrialResult, grade: GradeResult,
    attribution: FailureAttribution, *, adapter_result: AgentRunResult | None = None,
) -> None:
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "config.json").write_text(json.dumps(config_meta, indent=2))
    (trial_dir / "patch.diff").write_text(trial.patch)
    with (trial_dir / "trajectory.jsonl").open("w") as fh:
        for ev in trial.events:
            fh.write(ev.model_dump_json() + "\n")
    (trial_dir / "grader-results.json").write_text(grade.model_dump_json(indent=2))
    (trial_dir / "failure-tags.json").write_text(attribution.model_dump_json(indent=2))
    if adapter_result is not None:
        adapter_result = _relocate_native_trajectory(adapter_result, trial_dir)
        (trial_dir / "agent-result.json").write_text(adapter_result.model_dump_json(indent=2))


def _relocate_native_trajectory(result: AgentRunResult, trial_dir: Path) -> AgentRunResult:
    """Move an external agent's raw trajectory next to the trial it belongs to.

    A trial directory has to be self-contained: it is the unit that gets archived, diffed and
    turned into a reproduction bundle, and a pointer into a shared staging directory breaks the
    moment that directory is cleaned or the run is copied to another machine.
    """
    source = Path(result.native_trajectory_path) if result.native_trajectory_path else None
    if source is None or not source.exists():
        return result

    native_dir = trial_dir / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    destination = native_dir / source.name
    shutil.move(str(source), destination)
    for companion in source.parent.glob(f"{source.stem}.*"):
        if companion.is_file():
            shutil.move(str(companion), native_dir / companion.name)
    return result.model_copy(update={"native_trajectory_path": str(destination)})


# --------------------------------------------------------------------------- #
# Experiment (cases x repeats) + aggregation
# --------------------------------------------------------------------------- #
def _aggregate_case(
    case_id: str, grades: list[GradeResult], trials: list[TrialResult], attrs: list[FailureAttribution]
) -> dict[str, Any]:
    k = len(grades)
    if not (k == len(trials) == len(attrs)):
        raise ValueError("grades, trials, and attributions must have equal lengths")
    valid_indexes = [i for i, trial in enumerate(trials) if not _is_infra_invalid(trial)]
    valid_grades = [grades[i] for i in valid_indexes]
    valid_trials = [trials[i] for i in valid_indexes]
    task = [g.task_success for g in valid_grades]
    strict = [g.strict_success for g in valid_grades]
    tool_calls = [t.tool_call_count for t in valid_trials]
    durations = [t.duration_ms for t in valid_trials]
    tokens = [sum(c.total_tokens for c in t.llm_calls) for t in valid_trials]
    model_steps = [t.steps for t in valid_trials]
    test_runs = [sum(event.type == TraceEventType.TEST_RESULT for event in t.events) for t in valid_trials]
    failed_test_runs = [
        sum(
            event.type == TraceEventType.TEST_RESULT and event.payload.get("exit_code") not in (0, None)
            for event in t.events
        )
        for t in valid_trials
    ]
    costs = [t.cost_usd for t in valid_trials if t.cost_usd is not None]
    cost_sources = sorted({t.cost_source for t in valid_trials})
    valid_count = len(valid_trials)
    infra_failures = k - valid_count
    failure_tags: dict[str, int] = {}
    for a in attrs:
        if a.failed and a.primary:
            failure_tags[a.primary] = failure_tags.get(a.primary, 0) + 1
    return {
        "case_id": case_id,
        "repeats": k,
        "valid_trials": valid_count,
        "infra_failures": infra_failures,
        "infra_failure_rate": round(infra_failures / k, 4) if k else 0.0,
        "task_success_rate": round(sum(task) / valid_count, 4) if valid_count else None,
        "strict_success_rate": round(sum(strict) / valid_count, 4) if valid_count else None,
        "pass_at_k": int(any(task)) if valid_count else None,
        "pass_pow_k": int(all(task)) if valid_count else None,
        "tool_calls_mean": round(statistics.mean(tool_calls), 2) if valid_count else None,
        "action_steps_mean": round(statistics.mean(tool_calls), 2) if valid_count else None,
        "tool_calls_std": round(statistics.pstdev(tool_calls), 2) if valid_count else None,
        "model_steps_mean": round(statistics.mean(model_steps), 2) if valid_count else None,
        "test_runs_mean": round(statistics.mean(test_runs), 2) if valid_count else None,
        "failed_test_runs_mean": round(statistics.mean(failed_test_runs), 2) if valid_count else None,
        "duration_ms_mean": round(statistics.mean(durations), 1) if valid_count else None,
        "tokens_mean": round(statistics.mean(tokens), 1) if valid_count else None,
        "cost_usd_mean": round(statistics.mean(costs), 6) if len(costs) == valid_count and costs else None,
        "cost_sources": cost_sources,
        "failure_tags": failure_tags,
    }


def _is_infra_invalid(trial: TrialResult) -> bool:
    """Provider/adapter execution failures are invalid trials, not zero-capability evidence."""
    return canonical_stop_reason(trial) == "error" or bool(trial.completion_checks.get("provider_error"))


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else str(value)


def _summary_adapter_name(kind: str) -> str:
    if kind in ("v1", "v2"):
        return "mini_agent"
    if kind in EXTERNAL_ADAPTERS:
        return kind
    return f"builtin_{kind}"


def run_experiment(
    kind: str,
    suite_dir: Path,
    provider,
    repeats: int,
    case_filter: list[str] | None,
    out_root: Path,
    max_completion_tokens: int = 2048,
    adapter_config=None,
) -> dict[str, Any]:
    suite = load_suite(suite_dir)
    clean_repo = suite.repo
    cases = [c for c in suite.cases if not case_filter or c.case_id in case_filter]
    experiment_id = f"{kind}-{utc_now_iso().replace(':', '').replace('-', '')}"
    out_dir = out_root / experiment_id
    build_root = Path(tempfile.mkdtemp(prefix="cae-run-"))

    print(f"Experiment {experiment_id}: {len(cases)} cases x {repeats} repeats (agent={kind})")
    per_case: list[dict[str, Any]] = []
    suite_trials: list[TrialResult] = []
    for case in cases:
        grades, trials, attrs = [], [], []
        for r in range(repeats):
            grade, trial, attribution = run_trial(
                kind,
                case,
                suite_dir,
                clean_repo,
                provider,
                build_root,
                out_dir,
                r,
                max_completion_tokens,
                adapter_config=adapter_config,
            )
            grades.append(grade)
            trials.append(trial)
            attrs.append(attribution)
            suite_trials.append(trial)
        agg = _aggregate_case(case.case_id, grades, trials, attrs)
        per_case.append(agg)
        print(f"  {case.case_id}: task={_format_rate(agg['task_success_rate'])} "
              f"strict={_format_rate(agg['strict_success_rate'])} "
              f"(pass@k={agg['pass_at_k']} pass^k={agg['pass_pow_k']}, tools≈{agg['tool_calls_mean']})")

    shutil.rmtree(build_root, ignore_errors=True)

    case_task_rates = [c["task_success_rate"] for c in per_case if c["task_success_rate"] is not None]
    case_strict_rates = [c["strict_success_rate"] for c in per_case if c["strict_success_rate"] is not None]
    total_trials = sum(c["repeats"] for c in per_case)
    valid_trials = sum(c["valid_trials"] for c in per_case)
    infra_failures = sum(c["infra_failures"] for c in per_case)
    valid_suite_trials = [trial for trial in suite_trials if not _is_infra_invalid(trial)]
    suite_action_steps = [trial.tool_call_count for trial in valid_suite_trials]
    suite_model_steps = [trial.steps for trial in valid_suite_trials]
    suite_test_runs = [
        sum(event.type == TraceEventType.TEST_RESULT for event in trial.events)
        for trial in valid_suite_trials
    ]
    suite_failed_test_runs = [
        sum(
            event.type == TraceEventType.TEST_RESULT and event.payload.get("exit_code") not in (0, None)
            for event in trial.events
        )
        for trial in valid_suite_trials
    ]
    summary = {
        "experiment_id": experiment_id,
        "agent": kind,
        "adapter": _summary_adapter_name(kind),
        "harness": kind if kind in ("v1", "v2") else None,
        "suite": suite.name,
        "repeats": repeats,
        # Run provenance — constant across the experiment, so a V1/V2 comparison is only valid
        # when these match (same model / provider / temperature / sampling).
        "run_config": _run_config(
            kind, provider, max_completion_tokens, adapter_config=adapter_config
        ),
        "cases": per_case,
        "total_trials": total_trials,
        "valid_trials": valid_trials,
        "infra_failures": infra_failures,
        "infra_failure_rate": round(infra_failures / total_trials, 4) if total_trials else 0.0,
        "action_steps_median": statistics.median(suite_action_steps) if suite_action_steps else None,
        "model_steps_median": statistics.median(suite_model_steps) if suite_model_steps else None,
        "test_runs_median": statistics.median(suite_test_runs) if suite_test_runs else None,
        "failed_test_runs_median": (
            statistics.median(suite_failed_test_runs) if suite_failed_test_runs else None
        ),
        "suite_task_success": round(statistics.mean(case_task_rates), 4) if case_task_rates else None,
        "suite_strict_success": round(statistics.mean(case_strict_rates), 4) if case_strict_rates else None,
        "created_at": utc_now_iso(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_csv(out_dir / "summary.csv", per_case)
    print(
        f"\nSuite: task={_format_rate(summary['suite_task_success'])} "
        f"strict={_format_rate(summary['suite_strict_success'])} "
        f"valid={valid_trials}/{total_trials} infra={infra_failures}"
    )
    print(f"Artifacts: {out_dir}")
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _experiment_exit_code(summary: dict[str, Any]) -> int:
    """Signal incomplete infrastructure separately from evaluated Agent failures."""
    return 3 if summary.get("infra_failures", 0) else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CodeAgent Eval Lab runner")
    parser.add_argument("--agent", choices=AGENT_KINDS, default=None, help="legacy V1/V2 or baseline selector")
    parser.add_argument("--adapter", choices=ADAPTER_NAMES, default=None)
    parser.add_argument("--harness", choices=("v1", "v2"), default="v2")
    parser.add_argument("--suite", default="datasets/mini_store_suite")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="*", help="filter to these case_ids")
    parser.add_argument("--out", default="artifacts/runs")
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=2048,
        help="per-model-turn output-token cap for MiniAgent (default preserves V1/V2 history)",
    )
    claude = parser.add_argument_group("claude_code adapter")
    claude.add_argument("--claude-cli", default="claude", help="path to the claude executable")
    claude.add_argument("--claude-model", default=None, help="--model passed to the CLI")
    claude.add_argument("--claude-permission-mode", default="bypassPermissions")
    claude.add_argument(
        "--claude-extra-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="extra CLI flag, repeatable (verify against the installed version first)",
    )
    claude.add_argument(
        "--claude-use-operator-config",
        action="store_true",
        help="read the operator's real ~/.claude instead of an isolated per-trial config; "
             "needed for OAuth auth but makes the run non-reproducible elsewhere",
    )
    args = parser.parse_args(argv)

    try:
        kind = _resolve_agent_kind(args.agent, args.adapter, args.harness)
    except ValueError as exc:
        parser.error(str(exc))

    adapter_config = None
    if kind == "claude_code":
        adapter_config = ClaudeCodeConfig(
            cli_path=args.claude_cli,
            model=args.claude_model,
            permission_mode=args.claude_permission_mode,
            extra_args=tuple(args.claude_extra_arg),
            isolate_config=not args.claude_use_operator_config,
        )
        # Fail before the first trial: an unavailable binary must not burn a whole experiment's
        # worth of materialization and grading only to raise on every case.
        probe = create_adapter(kind, config=adapter_config).probe()
        if not probe.available:
            print(f"ERROR: adapter={kind} unavailable. {probe.detail}", file=sys.stderr)
            return 2
        print(f"adapter={kind} version={probe.version}")

    provider = None
    if kind in ("v1", "v2"):
        from codeagent_eval.llm import LlmProvider
        from codeagent_eval.settings import load_settings

        provider = LlmProvider(load_settings())
        if not provider.enabled:
            print(f"ERROR: agent={kind} needs an LLM provider. {provider._availability_error()}",
                  file=sys.stderr)
            return 2

    if args.max_completion_tokens < 1:
        parser.error("--max-completion-tokens must be positive")

    summary = run_experiment(
        kind,
        Path(args.suite),
        provider,
        args.repeats,
        args.cases,
        Path(args.out),
        args.max_completion_tokens,
        adapter_config=adapter_config,
    )
    return _experiment_exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
