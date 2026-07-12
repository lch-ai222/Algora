"""HumanEval+ adapter — a real, function-level public benchmark (no per-task Docker).

Purpose (per plan §6.2): calibrate the base model's raw ability and check whether the harness
hurts simple tasks; NOT the headline result. Each problem: prompt the model for a complete
function, then execute it against BASE tests and the stricter PLUS tests (EvalPlus-style extra
edge cases) in a temp dir with a timeout. Metrics: Pass@1 (base), base/plus pass rate.

The bundled dataset is a curated HumanEval-style subset (`datasets/humaneval_plus/problems.jsonl`)
so it runs offline; the schema matches EvalPlus so real data drops in unchanged.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, Field

from codeagent_eval.llm import LlmProvider

_EXEC_TIMEOUT = 10


class HumanEvalProblem(BaseModel):
    task_id: str
    prompt: str
    entry_point: str
    canonical_solution: str  # complete reference function, for dataset self-check
    base_tests: str
    plus_tests: str = ""


class _Completion(BaseModel):
    code: str


class ProblemResult(BaseModel):
    task_id: str
    base_passed: bool = False
    plus_passed: bool = False
    timed_out: bool = False
    error: str | None = None
    latency_ms: int = 0


def load_problems(path: str | Path) -> list[HumanEvalProblem]:
    lines = Path(path).read_text().splitlines()
    return [HumanEvalProblem.model_validate_json(ln) for ln in lines if ln.strip()]


def run_program(code: str, tests: str, timeout: int = _EXEC_TIMEOUT) -> tuple[bool, str | None, bool]:
    """Run `code` followed by `tests` (plain asserts) in a temp dir. Returns (passed, error, timed_out)."""
    if not tests.strip():
        return True, None, False  # nothing to check
    with tempfile.TemporaryDirectory(prefix="cae-he-") as tmp:
        run_py = Path(tmp) / "run.py"
        run_py.write_text(code + "\n\n" + tests + "\n")
        try:
            proc = subprocess.run(
                [sys.executable, str(run_py)],
                capture_output=True, text=True, timeout=timeout, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout", True
        if proc.returncode == 0:
            return True, None, False
        return False, (proc.stderr or "").strip()[-300:], False


def get_completion(provider: LlmProvider, problem: HumanEvalProblem) -> str | None:
    system = (
        "You are a Python expert. Implement the requested function. Return JSON "
        '{"code": "<the complete function definition, correctly indented>"}. '
        "Include the full def with signature; no explanation, no markdown fences."
    )
    resp = provider.json_completion(
        system_prompt=system,
        user_prompt=f"Implement this function:\n\n{problem.prompt}",
        response_model=_Completion,
        temperature=0.0,
        call_site="humaneval.complete",
        prompt_version="humaneval_v1",
    )
    return resp.code if resp else None


def evaluate_problem(
    provider: LlmProvider, problem: HumanEvalProblem, timeout: int = _EXEC_TIMEOUT
) -> ProblemResult:
    started = perf_counter()
    code = get_completion(provider, problem)
    if code is None:
        return ProblemResult(task_id=problem.task_id, error=provider.last_error or "no completion",
                             latency_ms=int((perf_counter() - started) * 1000))
    base_ok, base_err, base_to = run_program(code, problem.base_tests, timeout)
    plus_ok, _, _ = run_program(code, problem.plus_tests, timeout) if base_ok else (False, None, False)
    return ProblemResult(
        task_id=problem.task_id,
        base_passed=base_ok,
        plus_passed=base_ok and plus_ok,
        timed_out=base_to,
        error=base_err,
        latency_ms=int((perf_counter() - started) * 1000),
    )


class HumanEvalSummary(BaseModel):
    suite: str = "humaneval_plus"
    n: int
    base_pass_rate: float
    plus_pass_rate: float
    pass_at_1: float  # == base_pass_rate for k=1 greedy
    timeout_rate: float
    error_rate: float
    latency_ms_mean: float
    results: list[ProblemResult] = Field(default_factory=list)


def run_humaneval_suite(
    provider: LlmProvider, problems: list[HumanEvalProblem], timeout: int = _EXEC_TIMEOUT
) -> HumanEvalSummary:
    results = [evaluate_problem(provider, p, timeout) for p in problems]
    n = len(results)
    base = sum(r.base_passed for r in results)
    plus = sum(r.plus_passed for r in results)
    return HumanEvalSummary(
        n=n,
        base_pass_rate=round(base / n, 4) if n else 0.0,
        plus_pass_rate=round(plus / n, 4) if n else 0.0,
        pass_at_1=round(base / n, 4) if n else 0.0,
        timeout_rate=round(sum(r.timed_out for r in results) / n, 4) if n else 0.0,
        error_rate=round(sum(1 for r in results if r.error) / n, 4) if n else 0.0,
        latency_ms_mean=round(statistics.mean([r.latency_ms for r in results]), 1) if n else 0.0,
        results=results,
    )


def selfcheck_dataset(problems: list[HumanEvalProblem], timeout: int = _EXEC_TIMEOUT) -> list[str]:
    """Return task_ids whose canonical solution fails base or plus tests (should be empty)."""
    bad = []
    for p in problems:
        base_ok, _, _ = run_program(p.canonical_solution, p.base_tests, timeout)
        plus_ok, _, _ = run_program(p.canonical_solution, p.plus_tests, timeout)
        if not (base_ok and plus_ok):
            bad.append(p.task_id)
    return bad


def to_json(summary: HumanEvalSummary) -> dict:
    return summary.model_dump()
