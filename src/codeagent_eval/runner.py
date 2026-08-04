"""CLI closed loop: run an agent over a suite, grade deterministically, aggregate, persist.

    python -m codeagent_eval.runner --agent v1 --suite datasets/mini_store_suite --repeats 3
    python -m codeagent_eval.runner --adapter mini_agent --harness v2 --suite datasets/mini_store_suite
    python -m codeagent_eval.runner --adapter claude_code --suite datasets/mini_store_long --workers 8
    python -m codeagent_eval.runner --agent v2 --suite ... --resume v2-20260804T050844Z

Agent kinds:
  v1 / v2      MiniAgent (needs an LLM provider configured in .env)
  reference    apply the known-good fix (upper bound; for the discrimination check)
  none         change nothing (lower bound; for the discrimination check)

Per trial we persist config.json / trajectory.jsonl / patch.diff / grader-results.json under
artifacts/runs/<experiment_id>/<case_id>/rep<k>/, and write summary.json + summary.csv with
mean+variance and pass@k (capability) vs pass^k (reliability).

Trials are the unit of scheduling and of checkpointing: each one materializes its own repo,
so `--workers N` runs N at a time, and each writes a completion marker last, so `--resume`
re-runs only what is missing. `--workers` defaults to 1 because parallelism changes provider
rate-limit behavior; aggregation always follows suite order, so a parallel run and a serial
run over the same trials produce identical summaries.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
import tempfile
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

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
from codeagent_eval.graders.constraint_grader import ConstraintGrade
from codeagent_eval.graders.patch_grader import PatchGrade
from codeagent_eval.graders.pytest_run import PytestOutcome, run_pytest
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.graders.test_grader import TestGrade
from codeagent_eval.models import AgentTask, TraceEvent, TraceEventType, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

AGENT_KINDS = ("v1", "v2", "reference", "none")

#: Bumped when a persisted trial's on-disk shape changes, so `--resume` refuses to mix
#: artifacts it cannot interpret rather than silently aggregating stale ones.
TRIAL_SCHEMA_VERSION = 1


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


def trial_dir(out_dir: Path, case_id: str, repeat: int) -> Path:
    return out_dir / case_id / f"rep{repeat}"


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
    # Everything aggregation reads, minus the events already written to trajectory.jsonl.
    # Without this a resumed experiment could only recover scores, not the trajectory-derived
    # metrics (tool calls, test runs, tokens), and its summary would silently differ.
    (trial_dir / "trial.json").write_text(trial.model_dump_json(indent=2, exclude={"events"}))
    if adapter_result is not None:
        adapter_result = _relocate_native_trajectory(adapter_result, trial_dir)
        (trial_dir / "agent-result.json").write_text(adapter_result.model_dump_json(indent=2))
    # Written last, on purpose: a trial interrupted mid-write leaves no marker and is re-run,
    # so `--resume` can never adopt a half-written directory.
    (trial_dir / "trial-complete.json").write_text(
        json.dumps({"schema_version": TRIAL_SCHEMA_VERSION, "completed_at": utc_now_iso()}, indent=2)
    )


def load_completed_trial(
    trial_dir: Path,
) -> tuple[GradeResult, TrialResult, FailureAttribution] | None:
    """Rehydrate a finished trial, or return None if it must be re-run.

    Any missing/unreadable artifact or an unknown schema version means re-run: adopting a
    partially written trial would corrupt the experiment in a way no later check could detect.
    """
    marker = trial_dir / "trial-complete.json"
    if not marker.is_file():
        return None
    try:
        if json.loads(marker.read_text()).get("schema_version") != TRIAL_SCHEMA_VERSION:
            return None
        grade = GradeResult.model_validate_json((trial_dir / "grader-results.json").read_text())
        attribution = FailureAttribution.model_validate_json(
            (trial_dir / "failure-tags.json").read_text()
        )
        payload = json.loads((trial_dir / "trial.json").read_text())
        payload["events"] = [
            json.loads(line)
            for line in (trial_dir / "trajectory.jsonl").read_text().splitlines()
            if line.strip()
        ]
        return grade, TrialResult.model_validate(payload), attribution
    except (OSError, ValueError):
        return None


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
# Trial scheduling: one picklable work unit per (case, repeat)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrialSpec:
    """A single trial, fully described by values that survive a process boundary.

    Live objects (the LLM provider holds an HTTP client) are deliberately absent: each worker
    builds its own, which is also the only safe arrangement — sharing one client across
    processes is not defined behavior.
    """

    kind: str
    case_id: str
    suite_dir: str
    out_dir: str
    build_root: str
    repeat: int
    max_completion_tokens: int = 2048
    adapter_config: Any = None


class TrialOutcome(NamedTuple):
    case_id: str
    repeat: int
    grade: GradeResult
    trial: TrialResult
    attribution: FailureAttribution


#: Per-process caches. Loading the suite and constructing a provider once per worker keeps a
#: pool of long-lived processes from repeating that work on every trial.
_WORKER_CACHE: dict[Any, Any] = {}


def _worker_suite(suite_dir: str):
    key = ("suite", suite_dir)
    if key not in _WORKER_CACHE:
        _WORKER_CACHE[key] = load_suite(Path(suite_dir))
    return _WORKER_CACHE[key]


def _worker_provider(kind: str):
    if kind not in ("v1", "v2"):
        return None
    if "provider" not in _WORKER_CACHE:
        from codeagent_eval.llm import LlmProvider
        from codeagent_eval.settings import load_settings

        _WORKER_CACHE["provider"] = LlmProvider(load_settings())
    return _WORKER_CACHE["provider"]


def execute_trial(spec: TrialSpec) -> TrialOutcome:
    """Run one trial. Never raises: a crash becomes an infra-invalid trial.

    A harness crash on trial 47 must not discard the 46 completed ones, and it must not be
    scored as the agent failing the case either — it is missing evidence, which is exactly
    what the infra-invalid tier records.
    """
    out_dir = Path(spec.out_dir)
    case: EvalCase | None = None
    try:
        suite = _worker_suite(spec.suite_dir)
        case = next(c for c in suite.cases if c.case_id == spec.case_id)
        grade, trial, attribution = run_trial(
            spec.kind,
            case,
            Path(spec.suite_dir),
            suite.repo,
            _worker_provider(spec.kind),
            Path(spec.build_root) / f"{spec.case_id}-rep{spec.repeat}",
            out_dir,
            spec.repeat,
            spec.max_completion_tokens,
            adapter_config=spec.adapter_config,
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        # Loading the suite is inside the try as well, so even an unresolvable case_id becomes
        # a recorded infra failure rather than a raise that the pool would surface as a dead
        # worker.
        case = case or placeholder_case(spec.case_id)
        grade, trial, attribution = harness_failure(case, spec, exc)
        _persist_trial(
            trial_dir(out_dir, spec.case_id, spec.repeat),
            {
                "agent": spec.kind,
                "case_id": spec.case_id,
                "task_type": case.task_type,
                "repeat": spec.repeat,
                "stop_reason": trial.stop_reason,
                "canonical_stop_reason": trial.canonical_stop_reason,
                "harness_error": trial.completion_checks.get("harness_error"),
            },
            trial,
            grade,
            attribution,
        )
    return TrialOutcome(spec.case_id, spec.repeat, grade, trial, attribution)


def placeholder_case(case_id: str) -> EvalCase:
    """Stand-in used only when a failure record is needed but the real case is unavailable."""
    return EvalCase(case_id=case_id, task_type="bugfix", instruction="<case unresolved>")


def harness_failure(
    case: EvalCase, spec: TrialSpec, exc: BaseException
) -> tuple[GradeResult, TrialResult, FailureAttribution]:
    """Zero-valued but structurally valid artifacts for a trial the harness could not run."""
    empty = PytestOutcome(node_ids=[], exit_code=None)
    grade = combine(
        case.case_id,
        TestGrade(
            target=empty,
            regression=empty,
            hidden=empty,
            target_passed=False,
            regression_passed=False,
            hidden_passed=False,
            functional_success=False,
        ),
        ConstraintGrade(
            forbidden_paths_touched=[],
            changed_file_count=0,
            over_file_limit=False,
            added_dependencies=False,
            ran_tests_before_finish=False,
            denied_command_used=False,
            violations=["harness failure: trial did not run"],
            passed=False,
        ),
        PatchGrade(
            has_patch=False,
            applies_cleanly=False,
            changed_files=[],
            changed_file_count=0,
            insertions=0,
            deletions=0,
            modified_tests=False,
            modified_test_files=[],
            passed=False,
        ),
    )
    detail = f"{type(exc).__name__}: {exc}"
    trial = TrialResult(
        stop_reason="harness_error",
        canonical_stop_reason="error",
        events=[
            TraceEvent(
                step=0,
                type=TraceEventType.ERROR,
                name="harness_error",
                payload={"error": detail, "traceback": _short_traceback(exc)},
            )
        ],
        completion_checks={"provider_error": True, "harness_error": detail},
        started_at=utc_now_iso(),
        finished_at=utc_now_iso(),
    )
    return grade, trial, attribute_failure(case, trial, grade)


def _short_traceback(exc: BaseException, limit: int = 4000) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return text if len(text) <= limit else f"…{text[-limit:]}"


def _run_specs(specs: list[TrialSpec], workers: int, suite, on_outcome) -> None:
    """Execute specs serially (workers=1) or across a process pool, streaming outcomes."""
    if workers == 1:
        for spec in specs:
            on_outcome(execute_trial(spec))
        return

    cases = {c.case_id: c for c in suite.cases}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(execute_trial, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 - a dead worker must not kill the run
                # execute_trial swallows its own errors, so reaching here means the process
                # itself died (OOM, signal, BrokenProcessPool). Record it the same way.
                case = cases.get(spec.case_id) or placeholder_case(spec.case_id)
                grade, trial, attribution = harness_failure(case, spec, exc)
                _persist_trial(
                    trial_dir(Path(spec.out_dir), spec.case_id, spec.repeat),
                    {"agent": spec.kind, "case_id": spec.case_id, "repeat": spec.repeat,
                     "stop_reason": trial.stop_reason, "harness_error": str(exc)},
                    trial,
                    grade,
                    attribution,
                )
                outcome = TrialOutcome(spec.case_id, spec.repeat, grade, trial, attribution)
            on_outcome(outcome)


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


def _experiment_fingerprint(
    kind: str, suite_name: str, repeats: int, cases: list[EvalCase], run_config: dict[str, Any]
) -> dict[str, Any]:
    """The identity a resumed run must match to be the same experiment."""
    return {
        "agent": kind,
        "suite": suite_name,
        "repeats": repeats,
        "cases": [c.case_id for c in cases],
        "run_config": run_config,
    }


def _write_or_verify_manifest(out_dir: Path, fingerprint: dict[str, Any], *, resuming: bool) -> None:
    """Pin an experiment's identity so `--resume` cannot silently blend configurations.

    Resuming with a different model, harness or case set would produce one summary averaged
    over trials that were never comparable — a provenance failure invisible in the output.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    if resuming and manifest_path.is_file():
        previous = json.loads(manifest_path.read_text())
        if previous.get("fingerprint") != fingerprint:
            differing = sorted(
                key
                for key in set(fingerprint) | set(previous.get("fingerprint", {}))
                if previous.get("fingerprint", {}).get(key) != fingerprint.get(key)
            )
            raise ValueError(
                f"cannot resume {out_dir.name}: configuration differs from the original run "
                f"({', '.join(differing)}). Start a new experiment instead."
            )
        return
    if resuming:
        raise ValueError(f"cannot resume {out_dir.name}: no manifest.json found in {out_dir}")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": TRIAL_SCHEMA_VERSION,
                "created_at": utc_now_iso(),
                "fingerprint": fingerprint,
            },
            indent=2,
        )
    )


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
    workers: int = 1,
    resume_experiment_id: str | None = None,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    suite = load_suite(suite_dir)
    cases = [c for c in suite.cases if not case_filter or c.case_id in case_filter]
    run_config = _run_config(kind, provider, max_completion_tokens, adapter_config=adapter_config)

    experiment_id = resume_experiment_id or f"{kind}-{utc_now_iso().replace(':', '').replace('-', '')}"
    out_dir = out_root / experiment_id
    fingerprint = _experiment_fingerprint(kind, suite.name, repeats, cases, run_config)
    _write_or_verify_manifest(out_dir, fingerprint, resuming=resume_experiment_id is not None)
    build_root = Path(tempfile.mkdtemp(prefix="cae-run-"))

    # Reuse finished trials before scheduling anything, so a resumed run costs only what is
    # actually missing.
    completed: dict[tuple[str, int], TrialOutcome] = {}
    specs: list[TrialSpec] = []
    for case in cases:
        for repeat in range(repeats):
            done = load_completed_trial(trial_dir(out_dir, case.case_id, repeat))
            if done is not None:
                completed[(case.case_id, repeat)] = TrialOutcome(case.case_id, repeat, *done)
                continue
            specs.append(
                TrialSpec(
                    kind=kind,
                    case_id=case.case_id,
                    suite_dir=str(suite_dir),
                    out_dir=str(out_dir),
                    build_root=str(build_root),
                    repeat=repeat,
                    max_completion_tokens=max_completion_tokens,
                    adapter_config=adapter_config,
                )
            )

    total = len(cases) * repeats
    print(
        f"Experiment {experiment_id}: {len(cases)} cases x {repeats} repeats (agent={kind}, "
        f"workers={workers})"
    )
    if completed:
        print(f"  resumed: {len(completed)}/{total} trials already complete")

    finished = len(completed)

    def on_outcome(outcome: TrialOutcome) -> None:
        nonlocal finished
        finished += 1
        completed[(outcome.case_id, outcome.repeat)] = outcome
        status = "task=1" if outcome.grade.task_success else "task=0"
        if _is_infra_invalid(outcome.trial):
            status = f"INFRA ({outcome.trial.stop_reason})"
        print(f"  [{finished}/{total}] {outcome.case_id} rep{outcome.repeat}: {status}", flush=True)

    _run_specs(specs, workers, suite, on_outcome)
    shutil.rmtree(build_root, ignore_errors=True)

    # Aggregate in suite order regardless of completion order, so a parallel run and a serial
    # run over the same trials produce byte-identical summaries.
    per_case: list[dict[str, Any]] = []
    suite_trials: list[TrialResult] = []
    for case in cases:
        outcomes = [completed[(case.case_id, r)] for r in range(repeats)]
        agg = _aggregate_case(
            case.case_id,
            [o.grade for o in outcomes],
            [o.trial for o in outcomes],
            [o.attribution for o in outcomes],
        )
        per_case.append(agg)
        suite_trials.extend(o.trial for o in outcomes)
        print(f"  {case.case_id}: task={_format_rate(agg['task_success_rate'])} "
              f"strict={_format_rate(agg['strict_success_rate'])} "
              f"(pass@k={agg['pass_at_k']} pass^k={agg['pass_pow_k']}, tools≈{agg['tool_calls_mean']})")

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
        "workers": workers,
        "resumed_trials": len(cases) * repeats - len(specs),
        # Run provenance — constant across the experiment, so a V1/V2 comparison is only valid
        # when these match (same model / provider / temperature / sampling).
        "run_config": run_config,
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
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel trials (default 1: serial, so calibrated baselines stay reproducible; "
             "parallelism changes provider rate-limit behavior and is therefore opt-in)",
    )
    parser.add_argument(
        "--resume",
        metavar="EXPERIMENT_ID",
        default=None,
        help="continue an experiment under --out, re-running only its incomplete trials",
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
    if args.workers < 1:
        parser.error("--workers must be positive")

    try:
        summary = run_experiment(
            kind,
            Path(args.suite),
            provider,
            args.repeats,
            args.cases,
            Path(args.out),
            args.max_completion_tokens,
            adapter_config=adapter_config,
            workers=args.workers,
            resume_experiment_id=args.resume,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _experiment_exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
