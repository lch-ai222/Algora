"""Deterministic multi-turn feedback without hidden-oracle leakage."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from codeagent_eval.benchmark.case import EvalCase, FeedbackRound
from codeagent_eval.graders.pytest_run import PytestOutcome, run_pytest
from codeagent_eval.sandbox import WorktreeSandbox


@dataclass(frozen=True)
class FeedbackTurn:
    index: int
    round_id: str
    feedback: str
    visible_outcome: PytestOutcome
    injected_files: tuple[str, ...]


def inject_feedback_round(
    workspace_root: str | Path,
    suite_dir: str | Path,
    case: EvalCase,
    round_: FeedbackRound,
) -> list[str]:
    """Reveal only the declared follow-up tests, never the hidden directory."""
    root = Path(workspace_root)
    source_root = Path(suite_dir) / "cases" / case.case_id / "turns" / round_.round_id
    written: list[str] = []
    for relative in round_.visible_test_files:
        source = source_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"missing multi-turn visible test: {source}")
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        written.append(relative)
    return written


def inject_all_feedback_tests(
    workspace_root: str | Path, suite_dir: str | Path, case: EvalCase
) -> list[str]:
    root = Path(workspace_root)
    written: list[str] = []
    if case.multi_turn is None:
        return written
    for round_ in case.multi_turn.rounds:
        missing = [path for path in round_.visible_test_files if not (root / path).exists()]
        if missing:
            written.extend(
                inject_feedback_round(
                    root,
                    suite_dir,
                    case,
                    round_.model_copy(update={"visible_test_files": missing}),
                )
            )
    return written


class FeedbackDriver:
    """Release fixed user requests and visible tests in order.

    The driver runs only the currently visible target tests. Hidden and regression tests are
    not accepted as inputs, so their output cannot accidentally become coaching feedback.
    """

    def __init__(self, case: EvalCase, suite_dir: str | Path) -> None:
        if case.multi_turn is None:
            raise ValueError("FeedbackDriver requires a multi-turn case")
        self.case = case
        self.suite_dir = Path(suite_dir)
        self._active_tests = list(case.visible_tests)
        self._next_round = 0

    @property
    def active_tests(self) -> tuple[str, ...]:
        return tuple(self._active_tests)

    def evaluate(self, sandbox: WorktreeSandbox) -> PytestOutcome:
        return run_pytest(sandbox, self._active_tests)

    def next_turn(self, sandbox: WorktreeSandbox) -> FeedbackTurn | None:
        if self._next_round >= len(self.case.multi_turn.rounds):
            return None
        outcome = self.evaluate(sandbox)
        round_ = self.case.multi_turn.rounds[self._next_round]
        written = inject_feedback_round(sandbox.root, self.suite_dir, self.case, round_)
        sandbox.checkpoint_harness_files(
            written, message=f"harness: reveal multi-turn round {round_.round_id}"
        )
        self._active_tests.extend(round_.visible_tests)
        self._active_tests = list(dict.fromkeys(self._active_tests))
        self._next_round += 1
        feedback = _render_feedback(round_, outcome)
        return FeedbackTurn(
            index=self._next_round,
            round_id=round_.round_id,
            feedback=feedback,
            visible_outcome=outcome,
            injected_files=tuple(written),
        )


def _render_feedback(round_: FeedbackRound, outcome: PytestOutcome) -> str:
    status = "passed" if outcome.all_passed else "failed"
    details = [*outcome.failed, *outcome.errors]
    evidence = ", ".join(details) if details else "no failing node was parsed"
    visible_tail = outcome.raw_tail[-2000:] if outcome.raw_tail else "<no pytest output>"
    return (
        f"Deterministic visible-test feedback: the currently disclosed tests {status}. "
        f"Visible evidence: {evidence}.\n"
        f"Visible pytest tail:\n{visible_tail}\n\n"
        f"User follow-up ({round_.round_id}): {round_.feedback}\n"
        "The follow-up acceptance tests are now visible in the repository. Preserve all "
        "earlier requirements and constraints, implement this change, run the relevant tests, "
        "then provide an updated final summary."
    )
