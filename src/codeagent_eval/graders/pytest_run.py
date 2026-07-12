"""Run pytest node ids inside a sandbox and parse per-test pass/fail.

Deterministic oracle used by the Test grader. Invokes ``python -m pytest -v`` on the given
node ids (through the sandbox command policy + timeout) and parses the verbose result lines,
so we know exactly which tests passed/failed — not just an aggregate.
"""

from __future__ import annotations

import re
import shlex

from pydantic import BaseModel

from codeagent_eval.sandbox.worktree import WorktreeSandbox

# e.g. "tests/test_x.py::test_y PASSED [ 33%]"
_RESULT_LINE = re.compile(r"^(?P<node>\S+::\S+|\S+\.py)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED)")


class PytestOutcome(BaseModel):
    node_ids: list[str]
    passed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    skipped: list[str] = []
    collected: int = 0
    exit_code: int | None = None
    timed_out: bool = False
    blocked: bool = False
    raw_tail: str = ""

    @property
    def all_passed(self) -> bool:
        """True only if pytest ran, nothing failed/errored, and at least one test ran."""
        if self.timed_out or self.blocked or self.exit_code is None:
            return False
        return not self.failed and not self.errors and self.collected > 0

    @property
    def pass_rate(self) -> float:
        total = len(self.passed) + len(self.failed) + len(self.errors)
        return round(len(self.passed) / total, 4) if total else 0.0


def run_pytest(sandbox: WorktreeSandbox, node_ids: list[str], timeout: int = 120) -> PytestOutcome:
    if not node_ids:
        return PytestOutcome(node_ids=[], collected=0, exit_code=None)
    targets = " ".join(shlex.quote(n) for n in node_ids)
    command = f"python -m pytest -v --no-header -p no:cacheprovider {targets}"
    result = sandbox.run(command, timeout=timeout)
    outcome = PytestOutcome(node_ids=node_ids, exit_code=result.exit_code)
    if result.blocked:
        outcome.blocked = True
        outcome.raw_tail = result.block_reason or ""
        return outcome
    if result.timed_out:
        outcome.timed_out = True
        return outcome

    for line in (result.stdout or "").splitlines():
        m = _RESULT_LINE.match(line.strip())
        if not m:
            continue
        node, status = m.group("node"), m.group("status")
        {"PASSED": outcome.passed, "FAILED": outcome.failed,
         "ERROR": outcome.errors, "SKIPPED": outcome.skipped}[status].append(node)
    outcome.collected = len(outcome.passed) + len(outcome.failed) + len(outcome.errors) + len(outcome.skipped)
    outcome.raw_tail = "\n".join((result.stdout or "").splitlines()[-15:])
    return outcome
