"""W1-1: long-horizon benchmark quality gates and deterministic anchors."""

from __future__ import annotations

from pathlib import Path

from codeagent_eval.benchmark import defect_files, load_suite
from codeagent_eval.runner import run_experiment

_ROOT = Path(__file__).resolve().parents[1]
_LONG_SUITE = _ROOT / "datasets" / "mini_store_long"


def test_long_suite_schema_and_isolation_contracts():
    suite = load_suite(_LONG_SUITE)
    assert suite.name == "mini_store_long"
    # A minimum and a coverage requirement rather than an exact count: the suite is meant to
    # grow — case count is the binding limit on every interval this project reports — and an
    # equality here would have to be edited each time, which is not a contract worth pinning.
    assert len(suite.cases) >= 4
    assert len({case.case_id for case in suite.cases}) == len(suite.cases)
    assert suite.repo != (_ROOT / "datasets" / "mini_store_src").resolve()
    assert {"bugfix", "spec", "refactor", "build"} <= {c.task_type for c in suite.cases}

    for case in suite.cases:
        assert case.horizon == "long"
        assert case.expected_steps is not None and case.expected_steps >= 12
        assert case.expected_tool_calls is not None and case.expected_tool_calls >= 25
        assert case.canary is not None
        assert case.canary.description in case.render_instruction()
        assert case.constraints.require_tests_run_before_finish is True
        assert case.constraints.max_changed_files == len(defect_files(_LONG_SUITE, case))
        assert case.hidden_tests, f"{case.case_id} has no hidden test"
        for node_id in case.hidden_tests:
            assert not (suite.repo / node_id.split("::", 1)[0]).exists()


def test_long_suite_reference_is_full_upper_bound(tmp_path: Path):
    summary = run_experiment("reference", _LONG_SUITE, None, 1, None, tmp_path)
    assert summary["suite_task_success"] == 1.0
    assert summary["suite_strict_success"] == 1.0
    assert summary["action_steps_median"] == 0
    assert summary["model_steps_median"] == 1


def test_long_suite_none_is_full_lower_bound(tmp_path: Path):
    summary = run_experiment("none", _LONG_SUITE, None, 1, None, tmp_path)
    assert summary["suite_task_success"] == 0.0
    assert summary["suite_strict_success"] == 0.0
