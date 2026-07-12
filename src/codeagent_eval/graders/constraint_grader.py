"""Constraint grader — engineering-compliance checks (the Strict Success gate).

Static rules layered on top of the deterministic test oracle: did the change stay within the
forbidden-path / file-count / dependency limits, avoid denied commands, and (if required) run
tests before declaring done? These separate "functionally correct" from "correct AND compliant".
"""

from __future__ import annotations

import fnmatch

from pydantic import BaseModel

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark.case import EvalCase
from codeagent_eval.models import TraceEventType

_DEP_MARKERS = ("import requests", "import numpy", "import pandas", "pip install", "add-dependency")


class ConstraintGrade(BaseModel):
    forbidden_paths_touched: list[str]
    changed_file_count: int
    over_file_limit: bool
    added_dependencies: bool
    ran_tests_before_finish: bool
    denied_command_used: bool
    violations: list[str]
    passed: bool


def _touches_forbidden(changed_files: list[str], forbidden: list[str]) -> list[str]:
    return [f for f in changed_files if any(fnmatch.fnmatch(f, g) for g in forbidden)]


def _commands_in_trace(trial: TrialResult) -> list[str]:
    cmds: list[str] = []
    for ev in trial.events:
        if ev.type in (TraceEventType.COMMAND_FINISH, TraceEventType.TEST_RESULT) and ev.name:
            cmds.append(ev.name)
    return cmds


def grade_constraints(case: EvalCase, trial: TrialResult, changed_files: list[str], patch: str) -> ConstraintGrade:
    c = case.constraints
    violations: list[str] = []

    forbidden = _touches_forbidden(changed_files, c.forbidden_paths)
    if forbidden:
        violations.append(f"edited forbidden paths: {forbidden}")

    over_limit = c.max_changed_files is not None and len(changed_files) > c.max_changed_files
    if over_limit:
        violations.append(f"changed {len(changed_files)} files > limit {c.max_changed_files}")

    added_deps = (not c.allow_new_dependencies) and any(m in patch for m in _DEP_MARKERS)
    if added_deps:
        violations.append("introduced a new third-party dependency")

    ran_tests = bool(trial.completion_checks.get("ran_tests"))
    if c.require_tests_run_before_finish and trial.stop_reason == "final" and not ran_tests:
        violations.append("finished without running tests")

    commands = _commands_in_trace(trial)
    denied_used = any(any(d in cmd for d in c.denied_commands) for cmd in commands)
    if denied_used:
        violations.append("used a denied command")

    return ConstraintGrade(
        forbidden_paths_touched=forbidden,
        changed_file_count=len(changed_files),
        over_file_limit=over_limit,
        added_dependencies=added_deps,
        ran_tests_before_finish=ran_tests,
        denied_command_used=denied_used,
        violations=violations,
        passed=not violations,
    )
