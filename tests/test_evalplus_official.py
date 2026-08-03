"""Official EvalPlus smoke-slice adapter contracts (offline; no EvalPlus install required)."""

from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeagent_eval.benchmark.evalplus_official import (
    EvalPlusSmokeConfig,
    build_oracle_samples,
    dataset_sha256,
    generate_official_samples,
    generation_samples,
    generation_usage,
    load_evalplus_task_results,
    load_generation_trace_usage,
    parse_evalplus_pass_at_1,
    run_official_evaluator,
    sanitize_official_samples,
    select_official_problems,
    write_override_dataset,
)


def _problems(n: int = 8) -> dict[str, dict]:
    return {
        f"HumanEval/{idx}": {
            "task_id": f"HumanEval/{idx}",
            "prompt": f"def f{idx}(x):\n    \"\"\"Return x.\"\"\"\n",
            "canonical_solution": "    return x\n",
            "entry_point": f"f{idx}",
            "base_input": [[1]],
            "plus_input": [[-1]],
        }
        for idx in range(n)
    }


def test_config_rejects_duplicate_tasks_and_multi_sample():
    with pytest.raises(ValidationError):
        EvalPlusSmokeConfig(task_ids=["HumanEval/0", "HumanEval/0"])
    with pytest.raises(ValidationError):
        EvalPlusSmokeConfig(samples_per_task=2)


def test_seeded_selection_is_deterministic_and_sorted():
    problems = _problems()
    first = select_official_problems(problems, sample_size=3, seed=42)
    second = select_official_problems(problems, sample_size=3, seed=42)
    assert list(first) == list(second)
    assert list(first) == sorted(first, key=lambda task_id: int(task_id.split("/")[1]))


def test_explicit_selection_validates_unknown_ids():
    selected = select_official_problems(
        _problems(), sample_size=1, seed=0, task_ids=["HumanEval/3", "HumanEval/1"]
    )
    assert list(selected) == ["HumanEval/1", "HumanEval/3"]
    with pytest.raises(ValueError, match="unknown official"):
        select_official_problems(_problems(), sample_size=1, seed=0, task_ids=["HumanEval/99"])


def test_override_dataset_is_reproducible_and_oracle_joins_prompt(tmp_path: Path):
    selected = select_official_problems(_problems(), sample_size=2, seed=7)
    first = write_override_dataset(tmp_path / "a.jsonl.gz", selected)
    second = write_override_dataset(tmp_path / "b.jsonl.gz", selected)
    assert dataset_sha256(first) == dataset_sha256(second)
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert [row["task_id"] for row in rows] == list(selected)
    oracle = build_oracle_samples(selected)
    assert oracle[0]["solution"].startswith(selected[oracle[0]["task_id"]]["prompt"])
    assert oracle[0]["solution"].endswith("    return x\n")


def test_parse_evalplus_pass_at_1():
    stdout = "progress\nBase\n{'pass@1': 0.8}\nBase + Extra\n{'pass@1': 0.6}\n"
    assert parse_evalplus_pass_at_1(stdout) == (0.8, 0.6)
    release_stdout = (
        "humaneval (base tests)\npass@1:\t1.000\n"
        "humaneval+ (base + extra tests)\npass@1:\t0.800\n"
    )
    assert parse_evalplus_pass_at_1(release_stdout) == (1.0, 0.8)
    assert parse_evalplus_pass_at_1("no metrics") == (None, None)


def test_official_evaluator_builds_pinned_contract(tmp_path: Path):
    samples = tmp_path / "samples.jsonl"
    samples.write_text("{}\n")
    override = tmp_path / "selected.jsonl.gz"
    override.write_bytes(b"x")
    seen = {}

    def runner(command, cwd, env, timeout):
        seen.update(command=command, cwd=cwd, env=env, timeout=timeout)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Base\n{'pass@1': 1.0}\nBase + Extra\n{'pass@1': 1.0}\n",
            stderr="",
        )

    result = run_official_evaluator(
        python_executable=".venv-evalplus/bin/python",
        samples_path=samples,
        override_path=override,
        cwd=tmp_path,
        env={"HOME": "/tmp/home"},
        use_mini=True,
        parallel=1,
        timeout_seconds=30,
        runner=runner,
    )
    assert result.succeeded
    assert result.base_pass_at_1 == result.plus_pass_at_1 == 1.0
    assert seen["env"]["HUMANEVAL_OVERRIDE_PATH"] == str(override)
    assert seen["command"][-1] == "--mini"
    assert "--parallel" in seen["command"]
    assert "--i-just-wanna-run" not in seen["command"]


class _FakeProvider:
    last_error = None

    def json_completion(self, *, response_model, user_prompt, **kwargs):  # noqa: ARG002
        name = user_prompt.split("def ", 1)[1].split("(", 1)[0]
        return response_model(code=f"def {name}(x):\n    return x\n")


def test_generate_official_samples_uses_official_task_ids():
    selected = select_official_problems(_problems(), sample_size=2, seed=4)
    generated = generate_official_samples(_FakeProvider(), selected, temperature=0.0, max_tokens=500)
    samples = generation_samples(generated)
    assert [sample["task_id"] for sample in samples] == list(selected)
    assert all(sample["solution"].startswith("def f") for sample in samples)
    calls = []

    def sanitizer(code, entry_point):
        calls.append((code, entry_point))
        return code.strip()

    sanitized = sanitize_official_samples(selected, generated, sanitizer=sanitizer)
    assert [sample["task_id"] for sample in sanitized] == list(selected)
    assert [entry_point for _, entry_point in calls] == [
        selected[task_id]["entry_point"] for task_id in selected
    ]
    latency, tokens, cost = generation_usage(generated)
    assert latency >= 0 and tokens == 0 and cost == 0.0


def test_load_evalplus_task_results(tmp_path: Path):
    result_path = tmp_path / "results.json"
    result_path.write_text(
        json.dumps(
            {
                "eval": {
                    "HumanEval/2": [
                        {
                            "base_status": "pass",
                            "plus_status": "fail",
                            "base_fail_tests": [],
                            "plus_fail_tests": [[12]],
                        }
                    ]
                }
            }
        )
    )
    rows = load_evalplus_task_results(result_path)
    assert rows[0].task_id == "HumanEval/2"
    assert rows[0].base_status == "pass" and rows[0].plus_status == "fail"
    assert rows[0].plus_fail_count == 1


def test_load_generation_trace_usage(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "latency_ms": 12,
                "llm_calls": [{"total_tokens": 30, "estimated_cost_usd": 0.01}],
            }
        )
        + "\n"
    )
    assert load_generation_trace_usage(trace) == (12, 30, 0.01)
