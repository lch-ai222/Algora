"""W1-4: task planning for the MiniAgent, and the metric that keeps it honest.

A plan is self-reported. An agent can mark every item done and finish having written
nothing, and "5/5 items completed" would score that as perfect planning. So the tests here
are mostly about the gap between what the agent claims and what the repository shows.
"""

from __future__ import annotations

import json

import pytest

from codeagent_eval.adapters import BudgetContract, Capability, MiniAgentAdapter
from codeagent_eval.agent.loop import AgentConfig, MiniAgent
from codeagent_eval.agent.planner import (
    MAX_PLAN_ITEMS,
    PlanItem,
    PlanItemStatus,
    PlanTracker,
    PlanValidationError,
    parse_plan_items,
)
from codeagent_eval.agent.prompts import PROMPT_VERSIONS, build_system_prompt
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.sandbox import WorktreeSandbox
from codeagent_eval.tools import ToolContext, UpdatePlanTool, default_tools


def items(*specs) -> list[PlanItem]:
    return [PlanItem(id=i, text=f"step {i}", status=PlanItemStatus(s)) for i, s in specs]


# --------------------------------------------------------------------------- #
# Plan parsing: errors must be correctable by the model
# --------------------------------------------------------------------------- #
def test_a_well_formed_plan_parses():
    parsed = parse_plan_items(
        [{"id": "a", "text": "read pricing.py", "status": "in_progress"},
         {"id": "b", "text": "fix the tax rate", "status": "pending"}]
    )

    assert [i.id for i in parsed] == ["a", "b"]
    assert parsed[0].status is PlanItemStatus.IN_PROGRESS


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "non-empty"),
        ("not a list", "non-empty"),
        ([{"id": "a", "text": "", "status": "pending"}], "empty 'text'"),
        ([{"id": "a", "text": "x", "status": "finished"}], "unknown status"),
        ([{"id": "a", "text": "x", "status": "done"}, {"id": "a", "text": "y", "status": "done"}],
         "duplicate item id"),
        ([{"id": str(n), "text": "x", "status": "pending"} for n in range(MAX_PLAN_ITEMS + 1)],
         "at most"),
    ],
)
def test_malformed_plans_are_rejected_with_a_correctable_message(raw, message):
    with pytest.raises(PlanValidationError, match=message):
        parse_plan_items(raw)


def test_the_tool_returns_a_validation_error_instead_of_raising(git_repo):
    """A bad plan is something the model can fix next turn, not a trial-ending failure."""
    with WorktreeSandbox(git_repo) as sandbox:
        result = UpdatePlanTool().run(ToolContext(sandbox=sandbox), plan=[{"id": "a", "text": ""}])

    assert result.ok is False
    assert "invalid plan" in result.content
    assert "plan" not in result.data


def test_the_tool_echoes_the_plan_back_so_the_model_sees_its_own_state(git_repo):
    with WorktreeSandbox(git_repo) as sandbox:
        result = UpdatePlanTool().run(
            ToolContext(sandbox=sandbox),
            plan=[{"id": "a", "text": "fix add", "status": "done"},
                  {"id": "b", "text": "run tests", "status": "pending"}],
        )

    assert result.ok is True
    assert "[x] a: fix add" in result.content
    assert "[ ] b: run tests" in result.content
    assert "1 still open" in result.content


# --------------------------------------------------------------------------- #
# Adherence is judged against the repository, not the agent's claim
# --------------------------------------------------------------------------- #
def test_a_completion_backed_by_a_repo_action_counts():
    tracker = PlanTracker()
    tracker.record(1, items(("a", "in_progress")), actions_so_far=0)
    tracker.record(3, items(("a", "done")), actions_so_far=2)

    stats = tracker.stats()
    assert stats["plan_adherence"] == 1.0
    assert stats["plan_done_without_action"] == 0


def test_a_completion_with_no_action_in_between_is_plan_theatre():
    """The failure this metric exists for: every item done, nothing written."""
    tracker = PlanTracker()
    tracker.record(1, items(("a", "pending"), ("b", "pending")), actions_so_far=0)
    tracker.record(2, items(("a", "done"), ("b", "done")), actions_so_far=0)

    stats = tracker.stats()
    assert stats["plan_items_done"] == 2
    assert stats["plan_adherence"] == 0.0, "claiming completion is not completing"
    assert stats["plan_done_without_action"] == 2


def test_adherence_mixes_backed_and_unbacked_completions():
    tracker = PlanTracker()
    tracker.record(1, items(("a", "pending"), ("b", "pending")), actions_so_far=0)
    tracker.record(2, items(("a", "done"), ("b", "pending")), actions_so_far=1)
    tracker.record(3, items(("a", "done"), ("b", "done")), actions_so_far=1)

    stats = tracker.stats()
    assert stats["plan_adherence"] == 0.5
    assert stats["plan_done_without_action"] == 1


def test_reopening_an_item_withdraws_its_earlier_completion():
    tracker = PlanTracker()
    tracker.record(1, items(("a", "pending")), actions_so_far=0)
    tracker.record(2, items(("a", "done")), actions_so_far=1)
    tracker.record(3, items(("a", "in_progress")), actions_so_far=1)

    stats = tracker.stats()
    assert stats["plan_items_done"] == 0
    assert stats["plan_adherence"] == 0.0
    assert stats["plan_abandonment"] == 1.0


def test_an_item_born_done_is_bookkeeping_not_planning():
    """Writing the plan after the fact is legitimate, but it is not planning, so it is
    reported separately rather than counted as adherence."""
    tracker = PlanTracker()
    tracker.record(4, items(("a", "done")), actions_so_far=3)

    stats = tracker.stats()
    assert stats["plan_done_retroactively"] == 1
    assert stats["plan_adherence"] == 0.0


def test_abandonment_counts_items_still_open_at_the_end():
    tracker = PlanTracker()
    tracker.record(1, items(("a", "pending"), ("b", "pending"), ("c", "pending")), actions_so_far=0)
    tracker.record(2, items(("a", "done"), ("b", "pending"), ("c", "dropped")), actions_so_far=1)

    stats = tracker.stats()
    assert stats["plan_items_open"] == 1
    assert stats["plan_items_dropped"] == 1
    assert stats["plan_abandonment"] == pytest.approx(1 / 3, abs=1e-4)


def test_stats_are_safe_on_a_trial_that_never_planned():
    stats = PlanTracker().stats()

    assert stats["plan_declared"] is False
    assert stats["plan_items"] == 0
    assert stats["plan_adherence"] is None, "no plan is not the same as a plan scoring zero"


# --------------------------------------------------------------------------- #
# Harness wiring: V3 is V2 plus a planner and nothing else
# --------------------------------------------------------------------------- #
def test_v3_prompt_extends_v2_verbatim():
    """Anything else changing between them would make a V2/V3 delta unattributable."""
    assert PROMPT_VERSIONS == ("v1", "v2", "v3")
    assert build_system_prompt("v3").startswith(build_system_prompt("v2"))
    assert "update_plan" in build_system_prompt("v3")
    assert "update_plan" not in build_system_prompt("v2")


def test_only_v3_is_offered_the_planning_tool():
    assert "update_plan" not in [t.name for t in default_tools()]
    assert "update_plan" in [t.name for t in default_tools(planning=True)]


def test_capabilities_track_the_harness_and_its_ablations():
    """An ablated V3 is a different system, and its capability set has to say so — otherwise
    a comparison table would show two rows both claiming to plan."""
    assert MiniAgentAdapter(None, harness="v2").capabilities() == set()
    assert MiniAgentAdapter(None, harness="v3").capabilities() == {
        Capability.PLANNING, Capability.COMPACTION
    }
    assert MiniAgentAdapter(None, harness="v3", ablate=frozenset({"planner"})).capabilities() == {
        Capability.COMPACTION
    }
    assert MiniAgentAdapter(None, harness="v3", ablate=frozenset({"context"})).capabilities() == {
        Capability.PLANNING
    }
    with pytest.raises(ValueError, match="unsupported MiniAgent harness"):
        MiniAgentAdapter(None, harness="v4")
    with pytest.raises(ValueError, match="unknown ablation"):
        MiniAgentAdapter(None, harness="v3", ablate=frozenset({"memory"}))


def test_an_ablation_is_part_of_the_harness_identity():
    """Recording an ablated run as plain "v3" would make the artifact unreadable later."""
    assert MiniAgentAdapter(None, harness="v3").adapter_version.endswith("+v3")
    ablated = MiniAgentAdapter(None, harness="v3", ablate=frozenset({"context", "planner"}))
    assert ablated.adapter_version.endswith("+v3-no_context-no_planner")


class _PlanningProvider:
    """Plans, edits, marks the item done, then finishes."""

    last_error = None

    def __init__(self, turns):
        self._turns = list(turns)

    def tool_completion(self, **kwargs):  # noqa: ARG002
        return self._turns.pop(0)


def _call(name, **args):
    return LlmToolCall(call_id=name, name=name, arguments=args)


def _plan_turn(*specs):
    return LlmToolTurn(
        tool_calls=[
            _call("update_plan", plan=[{"id": i, "text": f"step {i}", "status": s} for i, s in specs])
        ]
    )


def _run(turns, git_repo):
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=8, timeout_seconds=60
        )
        agent = MiniAgent(_PlanningProvider(turns), AgentConfig(version="v3", enable_planner=True))
        return agent.run(task, sandbox)


def test_a_real_v3_trial_records_the_plan_and_scores_it_against_the_edit(git_repo):
    trial = _run(
        [
            _plan_turn(("fix", "in_progress")),
            LlmToolTurn(tool_calls=[
                _call("apply_patch", path="app.py",
                      old_str="return a - b  # bug: should be +", new_str="return a + b")
            ]),
            _plan_turn(("fix", "done")),
            LlmToolTurn(content="done", tool_calls=[]),
        ],
        git_repo,
    )

    assert trial.plan["stats"]["plan_adherence"] == 1.0
    assert trial.plan["stats"]["plan_revisions"] == 2
    assert trial.plan["items"][0]["status"] == "done"
    plan_events = [e for e in trial.events if e.type is TraceEventType.PLAN_UPDATE]
    assert len(plan_events) == 2
    assert plan_events[0].payload["actions_at_revision"] == 0
    assert plan_events[1].payload["actions_at_revision"] == 1


def test_a_v3_trial_that_only_claims_completion_scores_zero(git_repo):
    """The agent finishes with a fully-checked plan and an untouched repository."""
    trial = _run(
        [_plan_turn(("fix", "pending")), _plan_turn(("fix", "done")),
         LlmToolTurn(content="all done", tool_calls=[])],
        git_repo,
    )

    assert trial.plan["stats"]["plan_adherence"] == 0.0
    assert trial.plan["stats"]["plan_done_without_action"] == 1
    assert trial.completion_checks["has_changes"] is False


def test_v2_carries_no_plan_at_all(git_repo):
    """An empty plan on V2 means "no planner", not "a planner that produced nothing"."""
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=4, timeout_seconds=60
        )
        trial = MiniAgent(
            _PlanningProvider([LlmToolTurn(content="done", tool_calls=[])]),
            AgentConfig(version="v2"),
        ).run(task, sandbox)

    assert trial.plan == {}


def test_the_plan_survives_the_adapter_round_trip(git_repo):
    adapter = MiniAgentAdapter(
        _PlanningProvider([_plan_turn(("fix", "pending")), LlmToolTurn(content="x", tool_calls=[])]),
        harness="v3",
    )
    task = AgentTask(instruction="x", workspace_path="", max_steps=4, timeout_seconds=30)
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, task, BudgetContract(max_wall_clock_s=30), runtime=sandbox)
        result = adapter.run("x")
        adapter.cleanup()

    assert result.plan["stats"]["plan_declared"] is True
    assert result.to_trial_result().plan == result.plan
    assert json.loads(result.model_dump_json())["plan"]["items"][0]["id"] == "fix"


def test_plan_metrics_aggregate_only_over_trials_that_planned(git_repo):
    """Averaging adherence over systems that were never asked to plan would dilute it."""
    from codeagent_eval.failure_taxonomy import FailureAttribution
    from codeagent_eval.graders.result import GradeResult
    from codeagent_eval.runner import _aggregate_case

    planned = _run(
        [_plan_turn(("fix", "pending")), _plan_turn(("fix", "done")),
         LlmToolTurn(content="x", tool_calls=[])],
        git_repo,
    )
    unplanned = _run([LlmToolTurn(content="x", tool_calls=[])], git_repo)
    grade = GradeResult.model_construct(task_success=True, strict_success=True)
    attribution = FailureAttribution(case_id="c", failed=False)

    agg = _aggregate_case("c", [grade, grade], [planned, unplanned], [attribution, attribution])

    assert agg["plan_declared_rate"] == 0.5
    assert agg["plan_adherence_mean"] == 0.0  # only the planning trial contributes
    assert agg["plan_done_without_action_total"] == 1


def test_planner_is_absent_from_the_default_config():
    """V1/V2 must keep exactly the toolset their calibrated baselines were measured with."""
    assert AgentConfig().enable_planner is False
    assert AgentConfig(version="v2").enable_planner is False
