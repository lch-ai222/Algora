"""M2 acceptance: the deterministic pipeline discriminates, and the graders catch bypasses.

Runs the full runner with the reference (upper bound) and none (lower bound) baselines — no
LLM needed — and unit-checks the patch/constraint guardrails that separate Task from Strict.
"""

from __future__ import annotations

from pathlib import Path

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import load_suite
from codeagent_eval.graders import grade_constraints, grade_patch
from codeagent_eval.runner import run_experiment

_SUITE = Path(__file__).resolve().parents[1] / "datasets" / "mini_store_suite"


def test_suite_loads_all_cases():
    suite = load_suite(_SUITE)
    assert len(suite.cases) == 9  # 6 base + 3 adversarial regression-traps
    assert {c.task_type for c in suite.cases} == {"bugfix", "spec"}
    assert sum(1 for c in suite.cases if "regression-trap" in c.tags) == 3


def test_reference_upper_bound_all_pass(tmp_path: Path):
    summary = run_experiment("reference", _SUITE, None, repeats=1, case_filter=None, out_root=tmp_path)
    assert summary["suite_task_success"] == 1.0
    assert summary["suite_strict_success"] == 1.0


def test_none_lower_bound_all_fail(tmp_path: Path):
    summary = run_experiment("none", _SUITE, None, repeats=1, case_filter=None, out_root=tmp_path)
    assert summary["suite_task_success"] == 0.0


def test_discrimination_reference_beats_none(tmp_path: Path):
    ref = run_experiment("reference", _SUITE, None, 1, None, tmp_path / "ref")
    none = run_experiment("none", _SUITE, None, 1, None, tmp_path / "none")
    assert ref["suite_task_success"] > none["suite_task_success"]


def test_patch_grader_flags_modified_tests():
    patch = (
        "diff --git a/tests/test_pricing.py b/tests/test_pricing.py\n"
        "--- a/tests/test_pricing.py\n+++ b/tests/test_pricing.py\n"
        "@@ -1 +1 @@\n-    assert apply_tax(100.0) == 108.0\n+    assert True\n"
    )
    grade = grade_patch(patch, ["tests/test_pricing.py"], base_repo=None)
    assert grade.modified_tests is True
    assert grade.passed is False  # a test-tampering patch never passes


def test_constraint_grader_flags_forbidden_and_file_limit():
    suite = load_suite(_SUITE)
    case = next(c for c in suite.cases if c.case_id == "bugfix-pricing-tax")  # max_changed_files=1
    trial = TrialResult(stop_reason="final", completion_checks={"ran_tests": True})
    changed = ["mini_store/pricing.py", "tests/test_pricing.py"]  # touched tests + 2 files
    grade = grade_constraints(case, trial, changed, patch="")
    assert grade.passed is False
    assert grade.forbidden_paths_touched == ["tests/test_pricing.py"]
    assert grade.over_file_limit is True
