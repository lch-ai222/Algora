"""C: the SWE-bench adapter parses the official schema and runs the resolve flow (gold path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeagent_eval.benchmark.swebench import (
    SWEBenchInstance,
    load_instances,
    materialize_instance,
    run_instance,
)

_SUITE = Path(__file__).resolve().parents[1] / "datasets" / "swebench_compat"


def test_parses_official_json_string_fields():
    # The official dataset encodes FAIL_TO_PASS / PASS_TO_PASS as JSON strings.
    inst = SWEBenchInstance.model_validate(
        {
            "instance_id": "x__y-1",
            "repo": "x/y",
            "base_commit": "abc",
            "FAIL_TO_PASS": '["tests/test_a.py::t1"]',
            "PASS_TO_PASS": '["tests/test_b.py::t2"]',
        }
    )
    assert inst.fail_to_pass == ["tests/test_a.py::t1"]
    assert inst.pass_to_pass == ["tests/test_b.py::t2"]


def test_compat_sample_loads():
    insts = load_instances(_SUITE / "instances.jsonl")
    assert len(insts) == 1
    assert insts[0].fail_to_pass == ["tests/test_slug_strip.py::test_strips_whitespace"]
    assert insts[0].repo_local == "repo_src"


def test_gold_path_resolves():
    inst = load_instances(_SUITE / "instances.jsonl")[0]
    result = run_instance(inst, _SUITE, mode="gold")
    assert result.resolved is True
    assert result.fail_to_pass_passed and result.pass_to_pass_passed
    assert "Compatibility Sample" in result.note


def test_real_instance_needs_env_setup(tmp_path):
    inst = SWEBenchInstance(instance_id="real__1", repo="django/django", repo_local=None)
    with pytest.raises(NotImplementedError):
        materialize_instance(inst, _SUITE, tmp_path)


def test_agent_mode_requires_provider():
    inst = load_instances(_SUITE / "instances.jsonl")[0]
    with pytest.raises(ValueError):
        run_instance(inst, _SUITE, mode="agent", provider=None)
