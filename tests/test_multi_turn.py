"""W3-1 deterministic feedback, staged visible tests, and adapter continuation."""

from __future__ import annotations

from pathlib import Path

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import (
    EvalCase,
    FeedbackDriver,
    FeedbackRound,
    MultiTurnSpec,
    load_suite,
)
from codeagent_eval.failure_taxonomy import FailureAttribution
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask
from codeagent_eval.runner import _aggregate_case, _run_adapter_trial
from codeagent_eval.sandbox import WorktreeSandbox

ROOT = Path(__file__).resolve().parents[1]
MULTI_SUITE = ROOT / "datasets" / "mini_store_multiturn"


class ScriptedProvider:
    last_error = None

    def __init__(self, turns):
        self.turns = list(turns)

    def tool_completion(self, **kwargs):  # noqa: ARG002
        return self.turns.pop(0)


def make_case(suite_dir: Path) -> EvalCase:
    followup = suite_dir / "cases" / "multi" / "turns" / "round-2" / "tests"
    followup.mkdir(parents=True)
    (followup / "test_followup.py").write_text(
        "from app import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
    )
    hidden = suite_dir / "cases" / "multi" / "hidden"
    hidden.mkdir(parents=True)
    (hidden / "test_hidden_secret.py").write_text("HIDDEN_SENTINEL = 'never disclose me'\n")
    return EvalCase(
        case_id="multi",
        task_type="multi_turn",
        instruction="Fix addition first.",
        visible_tests=["test_app.py"],
        hidden_tests=["tests/test_hidden_secret.py"],
        max_steps=8,
        multi_turn=MultiTurnSpec(rounds=[FeedbackRound(
            round_id="round-2",
            feedback="Add multiply(a, b) while preserving addition.",
            visible_test_files=["tests/test_followup.py"],
            visible_tests=["tests/test_followup.py"],
        )]),
    )


#: Steps granted per turn, where a case's turns are its opening request plus its feedback
#: rounds. Measured rather than guessed: unconstrained, these cases spend 7-10 steps per turn
#: with a worst observed trial at 29 steps over three turns. The original budgets of 18-20 sat
#: below that, and two of three trials stopped on ``max_steps`` while still grading Task 1.00 —
#: so the headline said success and the multi-turn diagnostic said the protocol never finished.
STEPS_PER_TURN = 16


def test_committed_multiturn_suite_has_three_isolated_staged_cases():
    suite = load_suite(MULTI_SUITE)

    assert len(suite.cases) == 3
    assert {case.task_type for case in suite.cases} == {"multi_turn"}
    assert all(case.multi_turn and case.all_visible_tests for case in suite.cases)
    assert max(len(case.multi_turn.rounds) for case in suite.cases) == 2
    for case in suite.cases:
        for round_ in case.multi_turn.rounds:
            for path in round_.visible_test_files:
                assert not (suite.repo / path).exists(), "future-turn tests must not start visible"


def test_every_multiturn_case_budgets_steps_by_its_turn_count():
    """Steps must not be the binding constraint on a suite that measures interaction.

    Budget pressure is the long suite's subject, under a wall clock every framework enforces
    identically. Here a step cap that bites turns "did the agent handle the follow-up" into
    "did the agent have steps left when the follow-up arrived", and the two are not separable
    after the fact. The wall clock stays at 300s against 25-63s observed, so this is the only
    budget that could bind.
    """
    for case in load_suite(MULTI_SUITE).cases:
        turns = len(case.multi_turn.rounds) + 1
        assert case.max_steps == STEPS_PER_TURN * turns, (
            f"{case.case_id} has {turns} turns and must budget "
            f"{STEPS_PER_TURN * turns} steps, not {case.max_steps}"
        )


def test_feedback_reveals_only_visible_tests_and_advances_patch_baseline(
    git_repo: Path, tmp_path: Path
):
    case = make_case(tmp_path)
    with WorktreeSandbox(git_repo) as sandbox:
        turn = FeedbackDriver(case, tmp_path).next_turn(sandbox)
        assert turn is not None
        assert turn.visible_outcome.failed == ["test_app.py::test_add"]
        assert (sandbox.root / "tests/test_followup.py").is_file()
        assert not (sandbox.root / "tests/test_hidden_secret.py").exists()
        assert "HIDDEN_SENTINEL" not in turn.feedback
        assert sandbox.changed_files() == []
        (sandbox.root / "app.py").write_text("def add(a, b):\n    return a + b\n")
        assert sandbox.changed_files() == ["app.py"]
        assert "test_followup.py" not in sandbox.export_patch()


def test_runner_continues_v3_and_records_recovery_without_test_pollution(
    git_repo: Path, tmp_path: Path
):
    case = make_case(tmp_path)
    provider = ScriptedProvider([
        LlmToolTurn(content="I need concrete feedback", tool_calls=[]),
        LlmToolTurn(tool_calls=[LlmToolCall(call_id="repair", name="apply_patch", arguments={
            "path": "app.py",
            "old_str": "def add(a, b):\n    return a - b  # bug: should be +\n",
            "new_str": (
                "def add(a, b):\n    return a + b\n\n\n"
                "def multiply(a, b):\n    return a * b\n"
            ),
        })]),
        LlmToolTurn(content="follow-up fixed", tool_calls=[]),
    ])
    task = AgentTask(
        instruction=case.instruction,
        workspace_path="",
        case_id=case.case_id,
        harness_version="v3",
        max_steps=8,
    )
    with WorktreeSandbox(git_repo) as sandbox:
        trial, normalized = _run_adapter_trial(
            task, sandbox, case, provider, suite_dir=tmp_path
        )

    assert trial.completion_checks["multi_turn_completed"] is True
    assert trial.completion_checks["initial_visible_passed"] is False
    assert trial.completion_checks["final_visible_passed"] is True
    assert trial.completion_checks["recovered_visible"] is True
    assert trial.completion_checks["recovery_turn"] == 2
    assert trial.completion_checks["feedback_rounds_delivered"] == 1
    assert normalized.steps == 3
    assert normalized.changed_files == ["app.py"]
    assert "test_followup.py" not in normalized.patch


def test_case_aggregation_reports_recovery_only_over_initial_failures():
    trials = [
        TrialResult(stop_reason="final", completion_checks={
            "multi_turn": True, "multi_turn_completed": True,
            "initial_visible_passed": False, "recovered_visible": True,
        }),
        TrialResult(stop_reason="final", completion_checks={
            "multi_turn": True, "multi_turn_completed": True,
            "initial_visible_passed": False, "recovered_visible": False,
        }),
        TrialResult(stop_reason="final", completion_checks={
            "multi_turn": True, "multi_turn_completed": True,
            "initial_visible_passed": True, "recovered_visible": False,
        }),
    ]
    grades = [GradeResult.model_construct(task_success=True, strict_success=True) for _ in trials]
    attrs = [FailureAttribution(case_id="multi", failed=False) for _ in trials]

    summary = _aggregate_case("multi", grades, trials, attrs)

    assert summary["multi_turn_completion_rate"] == 1.0
    assert summary["initial_visible_failures"] == 2
    assert summary["visible_recoveries"] == 1
    assert summary["visible_recovery_rate"] == 0.5
