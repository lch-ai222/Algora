"""Failure attribution assigns the right primary cause from the trajectory + grade."""

from __future__ import annotations

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark.case import EvalCase
from codeagent_eval.failure_taxonomy import (
    CODE_RETRIEVAL,
    ENVIRONMENT,
    PREMATURE_TERMINATION,
    RECOVERY,
    TASK_UNDERSTANDING,
    TIMEOUT,
    attribute_failure,
)
from codeagent_eval.graders.constraint_grader import ConstraintGrade
from codeagent_eval.graders.patch_grader import PatchGrade
from codeagent_eval.graders.pytest_run import PytestOutcome
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.graders.test_grader import TestGrade
from codeagent_eval.models import TraceEvent, TraceEventType


def _case() -> EvalCase:
    return EvalCase(case_id="c", task_type="bugfix", instruction="x")


def _grade(target=True, regression=True, hidden=True, modified_tests=False, task=False) -> GradeResult:
    empty = PytestOutcome(node_ids=[])
    test = TestGrade(
        target=empty, regression=empty, hidden=empty,
        target_passed=target, regression_passed=regression, hidden_passed=hidden,
        functional_success=target and regression and hidden,
    )
    constraint = ConstraintGrade(
        forbidden_paths_touched=[], changed_file_count=1, over_file_limit=False,
        added_dependencies=False, ran_tests_before_finish=True, denied_command_used=False,
        violations=[], passed=True,
    )
    patch = PatchGrade(
        has_patch=True, applies_cleanly=True, changed_files=["a.py"], changed_file_count=1,
        insertions=1, deletions=0, modified_tests=modified_tests, modified_test_files=[], passed=not modified_tests,
    )
    return GradeResult(case_id="c", test=test, constraint=constraint, patch=patch,
                       task_success=task, strict_success=False)


def test_success_is_not_attributed():
    trial = TrialResult(stop_reason="final")
    attr = attribute_failure(_case(), trial, _grade(task=True))
    assert attr.failed is False and attr.primary is None


def test_incomplete_fix_is_premature_termination():
    # target passed, regression failed, agent finished without running regression
    trial = TrialResult(stop_reason="final", completion_checks={"has_changes": True},
                        events=[TraceEvent(type=TraceEventType.FILE_READ, name="a.py")])
    attr = attribute_failure(_case(), trial, _grade(target=True, regression=False))
    assert attr.primary == PREMATURE_TERMINATION


def test_saw_failing_test_then_stopped_is_recovery():
    trial = TrialResult(
        stop_reason="final",
        completion_checks={"has_changes": True},
        events=[
            TraceEvent(type=TraceEventType.FILE_READ, name="a.py"),
            TraceEvent(type=TraceEventType.TEST_RESULT, name="pytest", payload={"exit_code": 1}),
        ],
    )
    attr = attribute_failure(_case(), trial, _grade(target=True, regression=False))
    assert attr.primary == RECOVERY


def test_earlier_failure_recovered_but_hidden_miss_is_task_understanding():
    trial = TrialResult(
        stop_reason="final",
        completion_checks={"has_changes": True},
        events=[
            TraceEvent(type=TraceEventType.TEST_RESULT, name="pytest", payload={"exit_code": 1}),
            TraceEvent(type=TraceEventType.TEST_RESULT, name="pytest", payload={"exit_code": 0}),
        ],
    )
    attr = attribute_failure(_case(), trial, _grade(target=True, regression=True, hidden=False))
    assert attr.primary == TASK_UNDERSTANDING


def test_timeout_is_flagged():
    trial = TrialResult(stop_reason="timeout", completion_checks={"has_changes": True})
    attr = attribute_failure(_case(), trial, _grade(target=False))
    assert any(t.tag == TIMEOUT for t in attr.tags)


def test_no_read_no_target_is_code_retrieval():
    trial = TrialResult(stop_reason="final", completion_checks={"has_changes": True}, events=[])
    attr = attribute_failure(_case(), trial, _grade(target=False))
    assert any(t.tag == CODE_RETRIEVAL for t in attr.tags)


def test_provider_error_has_only_environment_tag():
    trial = TrialResult(stop_reason="provider_error", completion_checks={"has_changes": False})
    attr = attribute_failure(_case(), trial, _grade(target=False))
    assert attr.primary == ENVIRONMENT
    assert [tag.tag for tag in attr.tags] == [ENVIRONMENT]
