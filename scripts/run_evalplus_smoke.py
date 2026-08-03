#!/usr/bin/env python
"""Run a small official HumanEval+ slice through the pinned EvalPlus evaluator."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.benchmark.evalplus_official import (  # noqa: E402
    EvalPlusRunManifest,
    EvalPlusSmokeConfig,
    EvalPlusSmokeSummary,
    assert_evalplus_version,
    build_oracle_samples,
    configure_project_cache,
    dataset_sha256,
    evaluator_environment,
    generate_official_samples,
    generation_samples,
    generation_trace_rows,
    generation_usage,
    load_evalplus_task_results,
    load_generation_trace_usage,
    load_official_humaneval_plus,
    load_smoke_config,
    run_official_evaluator,
    sanitize_official_samples,
    select_official_problems,
    write_jsonl,
    write_manifest,
    write_override_dataset,
    write_summary,
)
from codeagent_eval.llm import LlmProvider  # noqa: E402
from codeagent_eval.models import utc_now_iso  # noqa: E402
from codeagent_eval.settings import load_settings  # noqa: E402

_DEFAULT_CONFIG = _ROOT / "config" / "benchmarks" / "evalplus_smoke.json"


def _run_id() -> str:
    return f"evalplus-smoke-{utc_now_iso().replace(':', '').replace('-', '')}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Official HumanEval+ smoke slice. Not a full benchmark or leaderboard run."
    )
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument("--selfcheck", action="store_true", help="run the official canonical oracle only")
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="call the model and sanitize samples, but do not execute generated code",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="evaluate model-samples-sanitized.jsonl from an earlier --generate-only run",
    )
    parser.add_argument(
        "--allow-local-model-execution",
        action="store_true",
        help="acknowledge that model-generated code will run without Docker isolation",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_smoke_config(args.config)
    updates = {}
    if args.sample_size is not None:
        updates["sample_size"] = args.sample_size
    if args.seed is not None:
        updates["selection_seed"] = args.seed
    if args.task_ids is not None:
        updates["task_ids"] = args.task_ids
    if updates:
        config = config.model_copy(update=updates)

    if args.selfcheck and (args.generate_only or args.resume):
        print("ERROR: --selfcheck cannot be combined with --generate-only/--resume", file=sys.stderr)
        return 2
    if args.generate_only and args.resume:
        print("ERROR: --generate-only and --resume are mutually exclusive", file=sys.stderr)
        return 2
    if config.evaluator_mode != "local_process":
        print("ERROR: official_docker is documented but not implemented in this environment", file=sys.stderr)
        return 2
    if not args.selfcheck and not args.generate_only and not args.allow_local_model_execution:
        print(
            "ERROR: official EvalPlus recommends Docker for untrusted code. "
            "Pass --allow-local-model-execution to acknowledge the current local-process limitation.",
            file=sys.stderr,
        )
        return 2

    if args.resume:
        return _resume_evaluation(args.resume.resolve(), config)

    run_id = _run_id()
    out = (args.out or (_ROOT / "artifacts" / "runs" / run_id)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = configure_project_cache(_ROOT, config.cache_dir)

    try:
        installed_version = assert_evalplus_version(config.evalplus_version)
        all_problems = load_official_humaneval_plus()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    selected = select_official_problems(
        all_problems,
        sample_size=config.sample_size,
        seed=config.selection_seed,
        task_ids=config.task_ids,
    )
    selected_ids = list(selected)
    override_path = write_override_dataset(out / "selected-problems.jsonl.gz", selected)
    oracle_samples_path = write_jsonl(out / "oracle-samples.jsonl", build_oracle_samples(selected))
    # Keep the virtualenv launcher path intact. Path.resolve() follows its symlink
    # to the system interpreter, which then loses the virtualenv site-packages.
    python_executable = Path(os.path.abspath(_ROOT / config.evalplus_python))
    if not python_executable.exists():
        print(f"ERROR: configured EvalPlus Python does not exist: {python_executable}", file=sys.stderr)
        return 2

    settings = load_settings()
    manifest = EvalPlusRunManifest(
        run_id=run_id,
        implementation_level=config.implementation_level,
        dataset=config.dataset,
        evalplus_version_expected=config.evalplus_version,
        evalplus_version_installed=installed_version,
        dataset_sha256=dataset_sha256(override_path),
        selection_method=("explicit_task_ids" if config.task_ids else "seeded_sample_before_generation"),
        selection_seed=config.selection_seed,
        selected_task_ids=selected_ids,
        sample_size=len(selected_ids),
        use_mini=config.use_mini,
        samples_per_task=config.samples_per_task,
        evaluator_mode=config.evaluator_mode,
        isolation_level=config.isolation_level,
        parallel=config.parallel,
        evalplus_max_memory_bytes=config.evalplus_max_memory_bytes,
        provider=None if args.selfcheck else settings.llm_provider,
        model=None if args.selfcheck else LlmProvider(settings).resolved_model(),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        limitations=[
            f"Only {len(selected_ids)} official tasks; results cannot estimate full HumanEval+ performance.",
            "HumanEvalPlus-Mini reduces extra tests for the resource-bounded smoke slice."
            if config.use_mini
            else "Full plus inputs are enabled for the selected tasks.",
            "Execution uses the official local evaluator without Docker isolation.",
            "EvalPlus memory rlimit is disabled for macOS compatibility; process isolation is not a security boundary."
            if config.evalplus_max_memory_bytes == -1
            else f"EvalPlus memory limit is {config.evalplus_max_memory_bytes} bytes.",
        ],
    )
    manifest_path = write_manifest(out / "manifest.json", manifest)
    env = evaluator_environment(cache, config.evalplus_max_memory_bytes)

    print(f"Official HumanEval+ smoke slice: {len(selected_ids)} tasks")
    print(f"  EvalPlus {installed_version} · mini={config.use_mini} · seed={config.selection_seed}")
    print(f"  task_ids={selected_ids}")
    print("  oracle: running official evaluator...")
    oracle = run_official_evaluator(
        python_executable=python_executable,
        samples_path=oracle_samples_path,
        override_path=override_path,
        cwd=_ROOT,
        env=env,
        use_mini=config.use_mini,
        parallel=config.parallel,
        timeout_seconds=config.evaluator_timeout_seconds,
    )
    (out / "oracle-evaluator.stdout.log").write_text(oracle.stdout, encoding="utf-8")
    (out / "oracle-evaluator.stderr.log").write_text(oracle.stderr, encoding="utf-8")
    oracle_valid = (
        oracle.succeeded and oracle.base_pass_at_1 == 1.0 and oracle.plus_pass_at_1 == 1.0
    )
    if not oracle_valid:
        summary = EvalPlusSmokeSummary(
            run_id=run_id,
            status="oracle_failed",
            selected_task_ids=selected_ids,
            n_selected=len(selected_ids),
            oracle_base_pass_at_1=oracle.base_pass_at_1,
            oracle_plus_pass_at_1=oracle.plus_pass_at_1,
            oracle_evaluator=oracle,
            manifest_path=str(manifest_path),
        )
        write_summary(out / "summary.json", summary)
        print(f"ERROR: official oracle failed; see {out}", file=sys.stderr)
        return 1

    print("  oracle: base=100% plus=100%")
    if args.selfcheck:
        summary = EvalPlusSmokeSummary(
            run_id=run_id,
            status="oracle_valid",
            selected_task_ids=selected_ids,
            n_selected=len(selected_ids),
            oracle_base_pass_at_1=oracle.base_pass_at_1,
            oracle_plus_pass_at_1=oracle.plus_pass_at_1,
            oracle_evaluator=oracle,
            manifest_path=str(manifest_path),
        )
        write_summary(out / "summary.json", summary)
        print(f"Artifacts: {out}")
        return 0

    provider = LlmProvider(settings)
    if not provider.enabled:
        print(f"ERROR: needs an LLM provider. {provider._availability_error()}", file=sys.stderr)
        return 2
    generated = generate_official_samples(
        provider,
        selected,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    write_jsonl(out / "generation-trace.jsonl", generation_trace_rows(generated))
    generation_latency_ms, total_tokens, estimated_cost_usd = generation_usage(generated)
    raw_samples = generation_samples(generated)
    write_jsonl(out / "model-samples.jsonl", raw_samples)
    failures = {row.task_id: row.error or "generation failed" for row in generated if row.solution is None}
    if failures:
        summary = EvalPlusSmokeSummary(
            run_id=run_id,
            status="generation_failed",
            selected_task_ids=selected_ids,
            n_selected=len(selected_ids),
            n_generated=len(raw_samples),
            generation_failures=failures,
            generation_latency_ms_total=generation_latency_ms,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            oracle_base_pass_at_1=oracle.base_pass_at_1,
            oracle_plus_pass_at_1=oracle.plus_pass_at_1,
            oracle_evaluator=oracle,
            manifest_path=str(manifest_path),
        )
        write_summary(out / "summary.json", summary)
        print(f"ERROR: {len(failures)} generation(s) failed; refusing a biased denominator", file=sys.stderr)
        return 1

    print(f"  generation: {len(raw_samples)}/{len(selected_ids)} samples")
    try:
        sanitized_samples = sanitize_official_samples(selected, generated)
    except RuntimeError as exc:
        print(f"ERROR: official sanitization failed: {exc}", file=sys.stderr)
        return 1
    sanitized_path = write_jsonl(out / "model-samples-sanitized.jsonl", sanitized_samples)
    if args.generate_only:
        summary = EvalPlusSmokeSummary(
            run_id=run_id,
            status="generated",
            selected_task_ids=selected_ids,
            n_selected=len(selected_ids),
            n_generated=len(sanitized_samples),
            generation_failures=failures,
            generation_latency_ms_total=generation_latency_ms,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            oracle_base_pass_at_1=oracle.base_pass_at_1,
            oracle_plus_pass_at_1=oracle.plus_pass_at_1,
            oracle_evaluator=oracle,
            manifest_path=str(manifest_path),
        )
        write_summary(out / "summary.json", summary)
        print("  generated code was not executed; resume inside the restricted environment:")
        print(
            f"  .venv-evalplus/bin/python scripts/run_evalplus_smoke.py --resume {out} "
            "--allow-local-model-execution"
        )
        print(f"Artifacts: {out}")
        return 0

    print("  evaluator: running official base + plus tests...")
    model_eval = run_official_evaluator(
        python_executable=python_executable,
        samples_path=sanitized_path,
        override_path=override_path,
        cwd=_ROOT,
        env=env,
        use_mini=config.use_mini,
        parallel=config.parallel,
        timeout_seconds=config.evaluator_timeout_seconds,
    )
    (out / "model-evaluator.stdout.log").write_text(model_eval.stdout, encoding="utf-8")
    (out / "model-evaluator.stderr.log").write_text(model_eval.stderr, encoding="utf-8")
    metrics_valid = model_eval.base_pass_at_1 is not None and model_eval.plus_pass_at_1 is not None
    status = "complete" if model_eval.succeeded and metrics_valid else "evaluation_failed"
    drop = None
    if model_eval.base_pass_at_1 is not None and model_eval.plus_pass_at_1 is not None:
        drop = round(model_eval.base_pass_at_1 - model_eval.plus_pass_at_1, 6)
    task_results = (
        load_evalplus_task_results(model_eval.result_path) if model_eval.result_path else []
    )
    summary = EvalPlusSmokeSummary(
        run_id=run_id,
        status=status,
        selected_task_ids=selected_ids,
        n_selected=len(selected_ids),
        n_generated=len(sanitized_samples),
        oracle_base_pass_at_1=oracle.base_pass_at_1,
        oracle_plus_pass_at_1=oracle.plus_pass_at_1,
        base_pass_at_1=model_eval.base_pass_at_1,
        plus_pass_at_1=model_eval.plus_pass_at_1,
        base_to_plus_drop=drop,
        generation_failures=failures,
        generation_latency_ms_total=generation_latency_ms,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        results=task_results,
        oracle_evaluator=oracle,
        model_evaluator=model_eval,
        manifest_path=str(manifest_path),
    )
    write_summary(out / "summary.json", summary)
    print(f"  Base pass@1: {model_eval.base_pass_at_1}")
    print(f"  Plus pass@1: {model_eval.plus_pass_at_1}")
    print(f"Artifacts: {out}")
    return 0 if status == "complete" else 1


def _resume_evaluation(out: Path, config: EvalPlusSmokeConfig) -> int:
    required = [
        out / "manifest.json",
        out / "summary.json",
        out / "selected-problems.jsonl.gz",
        out / "model-samples-sanitized.jsonl",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print(f"ERROR: resume artifacts missing: {missing}", file=sys.stderr)
        return 2
    manifest = EvalPlusRunManifest.model_validate_json(required[0].read_text(encoding="utf-8"))
    previous = EvalPlusSmokeSummary.model_validate_json(required[1].read_text(encoding="utf-8"))
    if previous.status not in {"generated", "complete", "evaluation_failed"}:
        print(
            f"ERROR: resume requires status=generated/complete/evaluation_failed, got {previous.status}",
            file=sys.stderr,
        )
        return 2
    installed_version = assert_evalplus_version(config.evalplus_version)
    if installed_version != manifest.evalplus_version_installed:
        print("ERROR: EvalPlus version changed since generation", file=sys.stderr)
        return 2
    if dataset_sha256(required[2]) != manifest.dataset_sha256:
        print("ERROR: selected dataset hash changed since generation", file=sys.stderr)
        return 2
    python_executable = Path(os.path.abspath(_ROOT / config.evalplus_python))
    cache = configure_project_cache(_ROOT, config.cache_dir)
    env = evaluator_environment(cache, config.evalplus_max_memory_bytes)
    print(f"Resuming official evaluation: {manifest.run_id}")
    model_eval = run_official_evaluator(
        python_executable=python_executable,
        samples_path=required[3],
        override_path=required[2],
        cwd=_ROOT,
        env=env,
        use_mini=manifest.use_mini,
        parallel=manifest.parallel,
        timeout_seconds=config.evaluator_timeout_seconds,
    )
    (out / "model-evaluator.stdout.log").write_text(model_eval.stdout, encoding="utf-8")
    (out / "model-evaluator.stderr.log").write_text(model_eval.stderr, encoding="utf-8")
    metrics_valid = model_eval.base_pass_at_1 is not None and model_eval.plus_pass_at_1 is not None
    status = "complete" if model_eval.succeeded and metrics_valid else "evaluation_failed"
    drop = None
    if model_eval.base_pass_at_1 is not None and model_eval.plus_pass_at_1 is not None:
        drop = round(model_eval.base_pass_at_1 - model_eval.plus_pass_at_1, 6)
    task_results = (
        load_evalplus_task_results(model_eval.result_path) if model_eval.result_path else []
    )
    trace_path = out / "generation-trace.jsonl"
    usage = (
        load_generation_trace_usage(trace_path)
        if trace_path.exists()
        else (
            previous.generation_latency_ms_total,
            previous.total_tokens,
            previous.estimated_cost_usd,
        )
    )
    summary = EvalPlusSmokeSummary(
        run_id=manifest.run_id,
        status=status,
        selected_task_ids=manifest.selected_task_ids,
        n_selected=previous.n_selected,
        n_generated=previous.n_generated,
        oracle_base_pass_at_1=previous.oracle_base_pass_at_1,
        oracle_plus_pass_at_1=previous.oracle_plus_pass_at_1,
        base_pass_at_1=model_eval.base_pass_at_1,
        plus_pass_at_1=model_eval.plus_pass_at_1,
        base_to_plus_drop=drop,
        generation_failures=previous.generation_failures,
        generation_latency_ms_total=usage[0],
        total_tokens=usage[1],
        estimated_cost_usd=usage[2],
        results=task_results,
        oracle_evaluator=previous.oracle_evaluator,
        model_evaluator=model_eval,
        manifest_path=str(required[0]),
    )
    write_summary(required[1], summary)
    print(f"  Base pass@1: {model_eval.base_pass_at_1}")
    print(f"  Plus pass@1: {model_eval.plus_pass_at_1}")
    print(f"Artifacts: {out}")
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
