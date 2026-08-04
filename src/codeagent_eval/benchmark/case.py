"""Eval case schema for the internal SWE-style benchmark.

Mirrors the OctoCodingBench-style split of check-level vs instance-level results:
a case carries visible/hidden/regression tests plus engineering constraints, so we can
report Task Success (target tests pass) separately from Strict Success (target + hidden +
regression pass AND constraints hold). Hidden tests live outside the sandbox and are only
injected at grading time, so the agent can never read or overfit to them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal["bugfix", "spec", "refactor", "review", "instruction", "build", "multi_turn"]
Difficulty = Literal["easy", "medium", "hard"]
Horizon = Literal["short", "long"]


class CanarySpec(BaseModel):
    """Persistent, objectively checkable constraint used by later drift detectors."""

    constraint_id: str
    description: str
    #: Name in ``detectors.context_amnesia.CHECKERS``. An unknown name raises rather than
    #: being skipped: a canary that is never evaluated would report perfect adherence.
    checker: str
    params: dict[str, Any] = Field(default_factory=dict)


class CaseConstraints(BaseModel):
    """Engineering guardrails checked deterministically by the Constraint grader."""

    forbidden_paths: list[str] = Field(default_factory=list)  # fnmatch globs (e.g. tests)
    max_changed_files: int | None = None
    allow_new_dependencies: bool = False
    require_tests_run_before_finish: bool = False
    denied_commands: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    case_id: str
    task_type: TaskType
    instruction: str
    base_commit: str = "HEAD"
    # Test node ids (pytest -k / file::test). Visible tests ship in the repo; hidden and
    # regression tests are stored in the case dir and injected only at grading time.
    visible_tests: list[str] = Field(default_factory=list)
    hidden_tests: list[str] = Field(default_factory=list)
    regression_tests: list[str] = Field(default_factory=list)
    # Files (relative to the case dir) copied into the workspace *at grade time only*.
    hidden_test_files: list[str] = Field(default_factory=list)
    constraints: CaseConstraints = Field(default_factory=CaseConstraints)
    reference_patch: str | None = None  # relative path to a .diff used by selfcheck
    max_steps: int = 20
    timeout_seconds: int = 300
    difficulty: Difficulty = "easy"
    tags: list[str] = Field(default_factory=list)
    horizon: Horizon = "short"
    expected_steps: int | None = Field(default=None, ge=1)  # model/tool-use rounds
    expected_tool_calls: int | None = Field(default=None, ge=1)  # individual tool actions
    canary: CanarySpec | None = None
    build_checks: list[str] = Field(default_factory=list)
    allow_test_edits: bool = False
    known_shortcuts: list[str] = Field(default_factory=list)

    def render_instruction(self) -> str:
        """Render the task prompt with its persistent canary constraint, if configured."""
        if self.canary is None:
            return self.instruction
        return (
            f"{self.instruction.rstrip()}\n\n"
            f"Persistent constraint ({self.canary.constraint_id}): {self.canary.description}"
        )


class Suite(BaseModel):
    """A named benchmark: a target repo path plus its cases."""

    name: str
    repo_path: str
    cases: list[EvalCase]

    @property
    def repo(self) -> Path:
        return Path(self.repo_path)


def load_suite(suite_dir: str | Path) -> Suite:
    """Load a suite from ``<suite_dir>/suite.json`` (repo_path is resolved relative to it)."""
    suite_dir = Path(suite_dir)
    data = json.loads((suite_dir / "suite.json").read_text())
    repo_path = (suite_dir / data["repo_path"]).resolve()
    cases = [EvalCase.model_validate(c) for c in data["cases"]]
    return Suite(name=data["name"], repo_path=str(repo_path), cases=cases)


def case_dir(suite_dir: str | Path, case_id: str) -> Path:
    return Path(suite_dir) / "cases" / case_id
