"""Official EvalPlus HumanEval+ smoke-slice adapter.

Algora owns selection, generation, provenance, and artifact persistence. The
official, pinned EvalPlus package owns dataset loading, optional sanitization,
program execution, base/plus grading, and pass@k. This module deliberately
keeps EvalPlus imports lazy so the main project environment and offline tests do
not require the benchmark's heavy optional dependency set.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from codeagent_eval.llm import LlmProvider, llm_trace_scope
from codeagent_eval.models import LlmCallRecord, utc_now_iso

_BASE_PATTERN = re.compile(r"(?m)^Base\s*\n(\{[^\n]+\})")
_PLUS_PATTERN = re.compile(r"(?m)^Base \+ Extra\s*\n(\{[^\n]+\})")
_BASE_TAB_PATTERN = re.compile(r"(?m)^humaneval \(base tests\)\s*\npass@1:\s*([0-9.]+)")
_PLUS_TAB_PATTERN = re.compile(
    r"(?m)^humaneval\+ \(base \+ extra tests\)\s*\npass@1:\s*([0-9.]+)"
)
_TASK_NUM_PATTERN = re.compile(r"/(\d+)$")


class EvalPlusSmokeConfig(BaseModel):
    schema_version: str = "algora.evalplus_smoke_config.v1"
    implementation_level: Literal["smoke_slice"] = "smoke_slice"
    dataset: Literal["humaneval"] = "humaneval"
    evalplus_version: str = "0.3.1"
    sample_size: int = Field(default=5, ge=1)
    selection_seed: int = 20260712
    task_ids: list[str] = Field(default_factory=list)
    use_mini: bool = True
    samples_per_task: int = Field(default=1, ge=1)
    temperature: float = 0.0
    max_tokens: int = Field(default=2048, ge=1)
    evaluator_mode: Literal["local_process", "official_docker"] = "local_process"
    isolation_level: str = "official_local_evaluator_no_container"
    parallel: int = Field(default=1, ge=1)
    evalplus_max_memory_bytes: int = -1
    evaluator_timeout_seconds: int = Field(default=600, ge=1)
    cache_dir: str = ".cache/evalplus"
    evalplus_python: str = ".venv-evalplus/bin/python"

    @model_validator(mode="after")
    def validate_sampling(self) -> EvalPlusSmokeConfig:
        if self.samples_per_task != 1:
            raise ValueError("the first smoke-slice protocol supports samples_per_task=1 only")
        if self.task_ids and len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_ids must be unique")
        return self


class EvalPlusCommandResult(BaseModel):
    command: list[str]
    returncode: int
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    base_pass_at_1: float | None = None
    plus_pass_at_1: float | None = None
    result_path: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


class GenerationResult(BaseModel):
    task_id: str
    solution: str | None = None
    error: str | None = None
    latency_ms: int = 0
    llm_calls: list[LlmCallRecord] = Field(default_factory=list)


class EvalPlusTaskResult(BaseModel):
    task_id: str
    base_status: str
    plus_status: str
    base_fail_count: int = 0
    plus_fail_count: int = 0


class EvalPlusRunManifest(BaseModel):
    artifact_schema: str = Field(
        default="algora.evalplus_smoke_manifest.v1", serialization_alias="schema"
    )
    run_id: str
    implementation_level: str
    dataset: str
    benchmark_name: str = "HumanEval+"
    evalplus_version_expected: str
    evalplus_version_installed: str
    dataset_sha256: str
    selection_method: str
    selection_seed: int
    selected_task_ids: list[str]
    sample_size: int
    use_mini: bool
    samples_per_task: int
    evaluator_mode: str
    isolation_level: str
    parallel: int
    evalplus_max_memory_bytes: int
    provider: str | None = None
    model: str | None = None
    prompt_version: str = "evalplus_official_v1"
    temperature: float = 0.0
    max_tokens: int = 0
    created_at: str = Field(default_factory=utc_now_iso)
    limitations: list[str] = Field(default_factory=list)


class EvalPlusSmokeSummary(BaseModel):
    artifact_schema: str = Field(
        default="algora.evalplus_smoke_summary.v1", serialization_alias="schema"
    )
    run_id: str
    status: Literal[
        "oracle_valid",
        "generated",
        "complete",
        "oracle_failed",
        "generation_failed",
        "evaluation_failed",
    ]
    implementation_level: str = "smoke_slice"
    benchmark_name: str = "HumanEval+"
    selected_task_ids: list[str]
    n_selected: int
    n_generated: int = 0
    oracle_base_pass_at_1: float | None = None
    oracle_plus_pass_at_1: float | None = None
    base_pass_at_1: float | None = None
    plus_pass_at_1: float | None = None
    base_to_plus_drop: float | None = None
    generation_failures: dict[str, str] = Field(default_factory=dict)
    generation_latency_ms_total: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    results: list[EvalPlusTaskResult] = Field(default_factory=list)
    oracle_evaluator: EvalPlusCommandResult
    model_evaluator: EvalPlusCommandResult | None = None
    manifest_path: str
    note: str = (
        "Official-instance smoke slice for protocol learning; not a full HumanEval+ "
        "benchmark result or leaderboard score."
    )


CommandRunner = Callable[[list[str], Path, Mapping[str, str], int], subprocess.CompletedProcess[str]]


def load_smoke_config(path: str | Path) -> EvalPlusSmokeConfig:
    return EvalPlusSmokeConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def installed_evalplus_version() -> str:
    try:
        return version("evalplus")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "EvalPlus is not installed. Create .venv-evalplus and install the project's "
            "[evalplus] optional dependency."
        ) from exc


def assert_evalplus_version(expected: str) -> str:
    installed = installed_evalplus_version()
    if installed != expected:
        raise RuntimeError(f"EvalPlus version mismatch: expected {expected}, installed {installed}")
    return installed


def configure_project_cache(project_root: Path, cache_dir: str) -> Path:
    """Keep third-party caches inside the project so they are inspectable and removable."""
    cache = (project_root / cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    home = cache / "home"
    xdg = cache / "xdg"
    home.mkdir(parents=True, exist_ok=True)
    xdg.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(home)
    os.environ["XDG_CACHE_HOME"] = str(xdg)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    return cache


def load_official_humaneval_plus() -> dict[str, dict[str, Any]]:
    """Load the official dataset lazily from the pinned EvalPlus package."""
    try:
        from evalplus.data import get_human_eval_plus
    except ImportError as exc:
        raise RuntimeError(
            "Cannot import EvalPlus. Run with .venv-evalplus/bin/python after installing "
            "the [evalplus] optional dependency."
        ) from exc
    problems = get_human_eval_plus()
    return {str(task_id): dict(problem) for task_id, problem in problems.items()}


def select_official_problems(
    problems: Mapping[str, Mapping[str, Any]],
    *,
    sample_size: int,
    seed: int,
    task_ids: Sequence[str] = (),
) -> dict[str, dict[str, Any]]:
    if task_ids:
        missing = sorted(set(task_ids) - set(problems))
        if missing:
            raise ValueError(f"unknown official HumanEval+ task_ids: {missing}")
        selected_ids = list(task_ids)
    else:
        if sample_size > len(problems):
            raise ValueError(f"sample_size {sample_size} exceeds dataset size {len(problems)}")
        selected_ids = random.Random(seed).sample(sorted(problems), sample_size)
    selected_ids.sort(key=_task_sort_key)
    return {task_id: dict(problems[task_id]) for task_id in selected_ids}


def write_override_dataset(path: str | Path, problems: Mapping[str, Mapping[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [dict(problems[task_id]) for task_id in sorted(problems, key=_task_sort_key)]
    _write_gzip_jsonl(destination, rows)
    return destination


def dataset_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_oracle_samples(problems: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for task_id in sorted(problems, key=_task_sort_key):
        problem = problems[task_id]
        prompt = str(problem["prompt"])
        canonical = str(problem["canonical_solution"])
        samples.append({"task_id": task_id, "solution": prompt + canonical})
    return samples


def write_jsonl(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    return destination


class _SolutionCompletion(BaseModel):
    code: str


def generate_official_samples(
    provider: LlmProvider,
    problems: Mapping[str, Mapping[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
) -> list[GenerationResult]:
    results: list[GenerationResult] = []
    system = (
        "You are completing an official HumanEval function. Return JSON "
        '{"code":"<self-contained Python solution>"}. Include every import and the complete '
        "function definition. Do not include explanations or markdown fences."
    )
    for task_id in sorted(problems, key=_task_sort_key):
        started = perf_counter()
        with llm_trace_scope(case_id=task_id, node_name="evalplus.generate") as calls:
            response = provider.json_completion(
                system_prompt=system,
                user_prompt=f"Implement the following function exactly as specified:\n\n{problems[task_id]['prompt']}",
                response_model=_SolutionCompletion,
                temperature=temperature,
                max_tokens=max_tokens,
                call_site="evalplus.official.complete",
                prompt_version="evalplus_official_v1",
            )
        results.append(
            GenerationResult(
                task_id=task_id,
                solution=response.code if response else None,
                error=None if response else (provider.last_error or "no completion"),
                latency_ms=int((perf_counter() - started) * 1000),
                llm_calls=list(calls),
            )
        )
    return results


def generation_samples(results: Sequence[GenerationResult]) -> list[dict[str, str]]:
    return [
        {"task_id": result.task_id, "solution": result.solution}
        for result in results
        if result.solution is not None
    ]


def generation_trace_rows(results: Sequence[GenerationResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        rows.append(
            {
                "schema": "algora.evalplus_generation.v1",
                "task_id": result.task_id,
                "status": "success" if result.solution is not None else "failed",
                "error": result.error,
                "latency_ms": result.latency_ms,
                "llm_calls": [call.model_dump() for call in result.llm_calls],
            }
        )
    return rows


def generation_usage(results: Sequence[GenerationResult]) -> tuple[int, int, float]:
    latency_ms = sum(result.latency_ms for result in results)
    calls = [call for result in results for call in result.llm_calls]
    tokens = sum(call.total_tokens for call in calls)
    cost = round(sum(call.estimated_cost_usd for call in calls), 8)
    return latency_ms, tokens, cost


def load_generation_trace_usage(path: str | Path) -> tuple[int, int, float]:
    latency_ms = 0
    tokens = 0
    cost = 0.0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        latency_ms += int(row.get("latency_ms", 0))
        for call in row.get("llm_calls", []):
            tokens += int(call.get("total_tokens", 0))
            cost += float(call.get("estimated_cost_usd", 0.0))
    return latency_ms, tokens, round(cost, 8)


def load_evalplus_task_results(path: str | Path) -> list[EvalPlusTaskResult]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    evaluations = payload.get("eval", {})
    results: list[EvalPlusTaskResult] = []
    for task_id in sorted(evaluations, key=_task_sort_key):
        rows = evaluations[task_id]
        if not rows:
            continue
        row = rows[0]
        results.append(
            EvalPlusTaskResult(
                task_id=task_id,
                base_status=str(row.get("base_status", "unknown")),
                plus_status=str(row.get("plus_status", "unknown")),
                base_fail_count=len(row.get("base_fail_tests", [])),
                plus_fail_count=len(row.get("plus_fail_tests", [])),
            )
        )
    return results


def sanitize_official_samples(
    problems: Mapping[str, Mapping[str, Any]],
    results: Sequence[GenerationResult],
    *,
    sanitizer: Callable[[str, str | None], str] | None = None,
) -> list[dict[str, str]]:
    """Apply EvalPlus's official sanitizer without loading unrelated MBPP data.

    The EvalPlus CLI sanitizer eagerly loads both HumanEval+ and MBPP+. Calling
    its pure sanitizer function directly preserves the official code
    post-processing logic while keeping this HumanEval-only smoke slice small.
    """
    if sanitizer is None:
        try:
            from evalplus.sanitize import sanitize
        except ImportError as exc:
            raise RuntimeError("EvalPlus sanitizer is unavailable") from exc
        sanitizer = sanitize
    samples: list[dict[str, str]] = []
    for result in results:
        if result.solution is None:
            continue
        entry_point = str(problems[result.task_id]["entry_point"])
        samples.append(
            {
                "task_id": result.task_id,
                "solution": sanitizer(result.solution, entry_point),
            }
        )
    return samples


def run_official_evaluator(
    *,
    python_executable: str | Path,
    samples_path: Path,
    override_path: Path,
    cwd: Path,
    env: Mapping[str, str],
    use_mini: bool,
    parallel: int,
    timeout_seconds: int,
    runner: CommandRunner | None = None,
) -> EvalPlusCommandResult:
    command = [
        str(python_executable),
        "-m",
        "evalplus.evaluate",
        "--dataset",
        "humaneval",
        "--samples",
        str(samples_path),
        "--parallel",
        str(parallel),
    ]
    if use_mini:
        command.append("--mini")
    evaluator_env = dict(env)
    evaluator_env["HUMANEVAL_OVERRIDE_PATH"] = str(override_path)
    result = _run_command(command, cwd, evaluator_env, timeout_seconds, runner=runner)
    result.base_pass_at_1, result.plus_pass_at_1 = parse_evalplus_pass_at_1(result.stdout)
    result_path = samples_path.with_name(f"{samples_path.stem}_eval_results.json")
    if result_path.exists():
        result.result_path = str(result_path)
    return result


def parse_evalplus_pass_at_1(output: str) -> tuple[float | None, float | None]:
    base = _pass_at_1(_BASE_PATTERN.search(output))
    plus = _pass_at_1(_PLUS_PATTERN.search(output))
    if base is None:
        base = _numeric_match(_BASE_TAB_PATTERN.search(output))
    if plus is None:
        plus = _numeric_match(_PLUS_TAB_PATTERN.search(output))
    return base, plus


def evaluator_environment(cache_dir: Path, max_memory_bytes: int) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(cache_dir / "home")
    env["XDG_CACHE_HOME"] = str(cache_dir / "xdg")
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["EVALPLUS_MAX_MEMORY_BYTES"] = str(max_memory_bytes)
    return env


def write_manifest(path: str | Path, manifest: EvalPlusRunManifest) -> Path:
    destination = Path(path)
    destination.write_text(manifest.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    return destination


def write_summary(path: str | Path, summary: EvalPlusSmokeSummary) -> Path:
    destination = Path(path)
    destination.write_text(summary.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    return destination


def _run_command(
    command: list[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    *,
    runner: CommandRunner | None,
) -> EvalPlusCommandResult:
    started = perf_counter()
    invoke = runner or _subprocess_runner
    try:
        completed = invoke(command, cwd, env, timeout_seconds)
        return EvalPlusCommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=int((perf_counter() - started) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        return EvalPlusCommandResult(
            command=command,
            returncode=124,
            stdout=_timeout_text(exc.stdout),
            stderr="EvalPlus command timed out",
            duration_ms=int((perf_counter() - started) * 1000),
        )


def _subprocess_runner(
    command: list[str], cwd: Path, env: Mapping[str, str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _pass_at_1(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    parsed = ast.literal_eval(match.group(1))
    value = parsed.get("pass@1") if isinstance(parsed, dict) else None
    return float(value) if value is not None else None


def _numeric_match(match: re.Match[str] | None) -> float | None:
    return float(match.group(1)) if match is not None else None


def _task_sort_key(task_id: str) -> tuple[int, str]:
    match = _TASK_NUM_PATTERN.search(task_id)
    return (int(match.group(1)) if match else sys.maxsize, task_id)


def _write_gzip_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for row in rows:
                payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
                compressed.write(payload.encode("utf-8"))


def _timeout_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
