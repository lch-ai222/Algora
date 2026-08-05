"""Test grader — the primary deterministic oracle.

Runs the case's target, regression, and hidden tests in the post-trial workspace (hidden
tests must already be injected). Functional success = all three green. This is the highest
tier of the grading hierarchy: program verification before any static rule or LLM judge.
"""

from __future__ import annotations

from pydantic import BaseModel

from codeagent_eval.benchmark.case import EvalCase
from codeagent_eval.graders.pytest_run import PytestOutcome, run_pytest
from codeagent_eval.sandbox.worktree import WorktreeSandbox


class TestGrade(BaseModel):
    __test__ = False  # not a pytest test class despite the "Test" prefix

    target: PytestOutcome
    regression: PytestOutcome
    hidden: PytestOutcome
    target_passed: bool
    regression_passed: bool
    hidden_passed: bool
    functional_success: bool  # target AND regression AND hidden

    @property
    def hidden_pass_rate(self) -> float:
        return self.hidden.pass_rate

    @property
    def regression_pass_rate(self) -> float:
        return self.regression.pass_rate


def grade_tests(sandbox: WorktreeSandbox, case: EvalCase, timeout: int = 120) -> TestGrade:
    target = run_pytest(sandbox, case.all_visible_tests, timeout=timeout)
    regression = run_pytest(sandbox, case.regression_tests, timeout=timeout)
    hidden = run_pytest(sandbox, case.hidden_tests, timeout=timeout)
    tp, rp, hp = target.all_passed, regression.all_passed, hidden.all_passed
    return TestGrade(
        target=target,
        regression=regression,
        hidden=hidden,
        target_passed=tp,
        regression_passed=rp,
        hidden_passed=hp,
        functional_success=tp and rp and hp,
    )
