"""Failure attribution (plan §9).

Auto-tags a *failed* trial with a primary cause (and secondary causes) using deterministic
rules over the trajectory + grade. This turns raw failures into a taxonomy we can aggregate,
which is what drives the V1→V2 harness changes: fix the dominant failure modes, then re-run.

Rules are conservative and explainable; anything the rules can't place is UNKNOWN (a human
reviews the trace). The taxonomy labels follow the plan's §9 list.
"""

from __future__ import annotations

from pydantic import BaseModel

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark.case import EvalCase
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.models import TraceEventType

# §9 taxonomy
TIMEOUT = "TIMEOUT"
REPEATED_ACTION = "REPEATED_ACTION"
ENVIRONMENT = "ENVIRONMENT"
PLANNING = "PLANNING"
INSTRUCTION_VIOLATION = "INSTRUCTION_VIOLATION"
PREMATURE_TERMINATION = "PREMATURE_TERMINATION"
RECOVERY = "RECOVERY"
CODE_RETRIEVAL = "CODE_RETRIEVAL"
EDIT = "EDIT"
TASK_UNDERSTANDING = "TASK_UNDERSTANDING"
UNKNOWN = "UNKNOWN"


class FailureTag(BaseModel):
    tag: str
    reason: str


class FailureAttribution(BaseModel):
    case_id: str
    failed: bool
    primary: str | None = None
    tags: list[FailureTag] = []


def _saw_failing_test_then_finished(trial: TrialResult) -> bool:
    """A test_result with a non-zero exit appears, and the trial still ends with a final answer."""
    if trial.stop_reason != "final":
        return False
    for ev in trial.events:
        if ev.type == TraceEventType.TEST_RESULT and ev.payload.get("exit_code") not in (0, None):
            return True
    return False


def _read_any_source(trial: TrialResult) -> bool:
    return any(ev.type == TraceEventType.FILE_READ for ev in trial.events)


def attribute_failure(case: EvalCase, trial: TrialResult, grade: GradeResult) -> FailureAttribution:
    if grade.task_success:
        return FailureAttribution(case_id=case.case_id, failed=False)

    tags: list[FailureTag] = []

    # Terminal/mechanical causes first.
    if trial.stop_reason == "timeout":
        tags.append(FailureTag(tag=TIMEOUT, reason="trial exceeded the wall-clock budget"))
    if trial.stop_reason == "repeated_action":
        tags.append(FailureTag(tag=REPEATED_ACTION, reason="same action repeated past the guard limit"))
    if trial.stop_reason == "provider_error":
        tags.append(FailureTag(tag=ENVIRONMENT, reason="LLM provider call failed"))
    if trial.stop_reason == "max_steps":
        tags.append(FailureTag(tag=PLANNING, reason="ran out of steps before finishing"))

    # Compliance / tampering.
    if grade.patch.modified_tests or grade.constraint.forbidden_paths_touched:
        tags.append(FailureTag(tag=INSTRUCTION_VIOLATION, reason="edited forbidden/test files"))

    # Editing / understanding.
    if not trial.completion_checks.get("has_changes"):
        tags.append(FailureTag(tag=EDIT, reason="finished without changing any source"))

    # The signature regression-trap failure: target passed but regression/hidden failed and the
    # agent stopped — an incomplete fix shipped without full verification.
    if grade.test.target_passed and not (grade.test.regression_passed and grade.test.hidden_passed):
        if _saw_failing_test_then_finished(trial):
            tags.append(FailureTag(tag=RECOVERY, reason="a test was failing but the trial stopped anyway"))
        else:
            tags.append(FailureTag(
                tag=PREMATURE_TERMINATION,
                reason="target test passed but regression/hidden failed; finished without running them",
            ))

    if not grade.test.target_passed and not _read_any_source(trial):
        tags.append(FailureTag(tag=CODE_RETRIEVAL, reason="never read the source before editing"))

    if not tags:
        tags.append(FailureTag(tag=UNKNOWN, reason="no rule matched; review the trajectory"))

    return FailureAttribution(case_id=case.case_id, failed=True, primary=tags[0].tag, tags=tags)
