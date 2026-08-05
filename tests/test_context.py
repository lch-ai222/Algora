"""W2-1: context management — tiered truncation and deterministic compaction.

Compaction is the one thing in the harness that deliberately destroys information, so the
tests concentrate on what must survive it: a conversation the provider will still accept, the
task statement, and a record of what was dropped. A compaction that corrupts the message
sequence would fail every subsequent turn for a reason the trace could not explain.
"""

from __future__ import annotations

import pytest

from codeagent_eval.adapters import BudgetContract, MiniAgentAdapter
from codeagent_eval.agent.context import (
    DEFAULT_TOOL_OUTPUT_LIMIT,
    HARD_OUTPUT_LIMIT,
    ContextManager,
    _safe_tail_start,
    estimate_tokens,
    truncate,
)
from codeagent_eval.agent.loop import AgentConfig, MiniAgent
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.sandbox import WorktreeSandbox


def manager(**over) -> ContextManager:
    return ContextManager(**{"budget_tokens": 1000, "keep_recent_messages": 4, **over})


def convo(turns: int) -> list[dict]:
    """A realistic message list: user task, then assistant/tool pairs."""
    messages: list[dict] = [{"role": "user", "content": "fix the bug"}]
    for n in range(turns):
        messages.append(
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}", "type": "function"}]}
        )
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": f"result {n}"})
    return messages


# --------------------------------------------------------------------------- #
# Truncation
# --------------------------------------------------------------------------- #
def test_truncation_keeps_both_ends():
    """The head names what was inspected and the tail usually holds the result or the error."""
    text = "HEAD" + "x" * 5000 + "TAIL"
    trimmed, dropped = truncate(text, 100)

    assert trimmed.startswith("HEAD")
    assert trimmed.endswith("TAIL")
    assert dropped == len(text) - 100
    assert "elided by context management" in trimmed


def test_short_output_is_untouched():
    assert truncate("small", 100) == ("small", 0)


def _pressured(mgr):
    """Report a measurement above the pressure threshold, the way a provider turn would."""
    mgr.observe(int(mgr.budget_tokens * mgr.warn_threshold) + 1)
    return mgr


def test_limits_are_per_tool_once_the_window_is_under_pressure():
    """Reading a file is worth more context than listing a directory."""
    mgr = _pressured(manager())
    long_text = "y" * 20_000

    assert len(mgr.truncate_tool_output("read_file", long_text)) < 6100
    assert len(mgr.truncate_tool_output("list_files", long_text)) < 2100
    assert len(mgr.truncate_tool_output("read_file", long_text)) > len(
        mgr.truncate_tool_output("list_files", long_text)
    )


def test_a_roomy_window_keeps_the_whole_output():
    """The defect this replaced: truncation was unconditional while compaction was not.

    At a 120s budget compaction fired in zero of sixteen trials because the trajectory peaked
    near 11k against 32k, and meanwhile every read was still being cut to 6000 characters. The
    harness paid for managing a window it never filled, and scored below the harness that
    manages nothing.
    """
    mgr = manager()
    mgr.observe(100)  # measured, and far below the threshold
    text = "y" * 20_000
    assert mgr.truncate_tool_output("read_file", text) == text
    assert mgr.stats.truncated_outputs == 0


def test_an_enormous_output_is_capped_even_with_room_to_spare():
    """One huge read can overrun the budget inside a step, before the next measurement exists."""
    mgr = manager()
    mgr.observe(100)
    trimmed = mgr.truncate_tool_output("read_file", "y" * (HARD_OUTPUT_LIMIT * 3))
    assert len(trimmed) < HARD_OUTPUT_LIMIT + 100
    assert mgr.stats.hard_capped_outputs == 1


def test_pressure_is_measured_never_estimated():
    """Before the provider has reported anything, a trial is not under pressure.

    Estimating here would reintroduce the char/4 heuristic the rest of this module avoids, and
    the estimate drifts per model and per tool schema.
    """
    assert manager().under_pressure() is False


def test_an_unknown_tool_falls_back_to_the_default_limit():
    mgr = _pressured(manager())
    assert len(mgr.truncate_tool_output("some_new_tool", "z" * 9999)) <= (
        DEFAULT_TOOL_OUTPUT_LIMIT + 100
    )


def test_truncation_is_counted_for_the_trial_record():
    mgr = _pressured(manager())
    mgr.truncate_tool_output("read_file", "y" * 20_000)
    mgr.truncate_tool_output("read_file", "short")

    stats = mgr.stats.as_dict(mgr.budget_tokens)
    assert stats["context_truncated_outputs"] == 1
    assert stats["context_truncated_chars"] > 0


# --------------------------------------------------------------------------- #
# Measurement drives the trigger
# --------------------------------------------------------------------------- #
def test_the_trigger_uses_the_provider_count_not_a_heuristic():
    """A char/4 estimate drifts per model and per tool schema, so a trigger built on it would
    fire at a different real size for each system under test."""
    mgr = manager(budget_tokens=1000, compaction_threshold=0.75)
    short_messages = [{"role": "user", "content": "hi"}]

    assert mgr.should_compact(short_messages) is False
    mgr.observe(800)  # the provider says the prompt was really this large
    assert mgr.should_compact(short_messages) is True


def test_the_heuristic_is_used_only_before_anything_is_measured():
    mgr = manager(budget_tokens=100)

    assert estimate_tokens([{"role": "user", "content": "x" * 4000}]) == 1000
    assert mgr.should_compact([{"role": "user", "content": "x" * 4000}]) is True


def test_a_provider_that_reports_no_usage_does_not_poison_the_measurement():
    mgr = manager()
    mgr.observe(500)
    mgr.observe(None)

    assert mgr.stats.last_prompt_tokens == 500


def test_peak_utilization_is_reported_against_the_budget():
    mgr = manager(budget_tokens=1000)
    mgr.observe(400)
    mgr.observe(900)
    mgr.observe(600)

    stats = mgr.stats.as_dict(mgr.budget_tokens)
    assert stats["context_peak_prompt_tokens"] == 900
    assert stats["context_peak_utilization"] == 0.9


# --------------------------------------------------------------------------- #
# Compaction must leave a conversation the provider still accepts
# --------------------------------------------------------------------------- #
def test_compaction_never_orphans_a_tool_result():
    """An assistant turn with tool_calls must be followed by a tool message for each call.
    Cutting between them produces a request the provider rejects outright."""
    messages = convo(10)

    for target in range(1, len(messages)):
        start = _safe_tail_start(messages, target)
        if start == len(messages):
            continue  # dropping the whole tail orphans nothing, which is also valid
        assert messages[start].get("role") != "tool", target
        assert not messages[start - 1].get("tool_calls"), target


def test_compaction_keeps_the_task_statement_and_the_recent_tail():
    mgr = manager(keep_recent_messages=4)
    messages = convo(8)
    mgr.observe(900)

    compacted, record = mgr.compact(messages, step=9, digest="- files written: app.py")

    assert compacted[0] == messages[0], "the task statement is never dropped"
    assert compacted[1]["role"] == "user" and "context compacted" in compacted[1]["content"]
    assert "app.py" in compacted[1]["content"]
    assert compacted[2:] == messages[len(messages) - len(compacted[2:]):]
    assert record.dropped_messages > 0
    assert len(compacted) < len(messages)


def test_a_short_conversation_is_left_alone():
    """Callers must not have to special-case the start of a trial."""
    messages = convo(1)
    compacted, record = manager().compact(messages, step=2, digest="x")

    assert compacted == messages
    assert record is None


def test_compaction_clears_the_stale_reading_so_it_does_not_retrigger():
    mgr = manager()
    mgr.observe(900)
    messages, _ = mgr.compact(convo(8), step=5, digest="x")

    assert mgr.should_compact(messages) is False


def test_invalid_configuration_is_rejected():
    for kwargs in ({"budget_tokens": 0}, {"compaction_threshold": 0}, {"keep_recent_messages": 1}):
        with pytest.raises(ValueError):
            manager(**kwargs)


# --------------------------------------------------------------------------- #
# In the loop
# --------------------------------------------------------------------------- #
class _StubProvider:
    """Returns scripted turns and reports a prompt size that grows past the budget."""

    last_error = None

    def __init__(self, turns, prompt_tokens=None):
        self._turns = list(turns)
        self._sizes = list(prompt_tokens or [])
        self.last_usage = None

    def tool_completion(self, **kwargs):  # noqa: ARG002
        if self._sizes:
            self.last_usage = {"prompt_tokens": self._sizes.pop(0)}
        return self._turns.pop(0)


def _read_turn(n):
    # Distinct paths per turn: identical arguments would trip the repeated-action guard that
    # V2 and V3 both carry, ending the trial before context management ever runs.
    return LlmToolTurn(
        tool_calls=[LlmToolCall(call_id=f"r{n}", name="read_file", arguments={"path": f"m{n}.py"})]
    )


def _run(git_repo, *, turns, sizes, **config_over):
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=12, timeout_seconds=60
        )
        config = AgentConfig.for_harness(
            "v3",
            enable_context_management=True,
            enforce_completion_checks=False,
            context_budget_tokens=1000,
            **config_over,
        )
        return MiniAgent(_StubProvider(turns, sizes), config).run(task, sandbox)


def test_a_trial_compacts_when_the_measured_prompt_crosses_the_threshold(git_repo):
    trial = _run(
        git_repo,
        turns=[_read_turn(n) for n in range(4)] + [LlmToolTurn(content="done", tool_calls=[])],
        sizes=[100, 200, 900, 950, 300],
    )

    events = [e for e in trial.events if e.type is TraceEventType.COMPACTION]
    assert events, "a compaction must be visible in the trace, not just in the message list"
    # Fires on the first turn that is both over threshold and long enough to have a safe cut,
    # so the recorded size is one of the over-budget readings rather than a fixed step.
    assert events[0].payload["before_tokens"] in (900, 950)
    assert events[0].payload["dropped_messages"] > 0
    assert trial.completion_checks["context_compactions"] == len(events)
    assert trial.completion_checks["context_budget_tokens"] == 1000


def test_the_digest_carries_what_the_dropped_turns_accomplished(git_repo):
    """Compaction destroys information on purpose; the agent still has to know what it did,
    or it repeats the work it can no longer see."""
    trial = _run(
        git_repo,
        turns=[_read_turn(n) for n in range(4)] + [LlmToolTurn(content="done", tool_calls=[])],
        sizes=[100, 200, 900, 950, 300],
    )

    assert any(e.payload["digest_chars"] > 0 for e in trial.events
               if e.type is TraceEventType.COMPACTION)


def test_a_trial_under_budget_never_compacts(git_repo):
    trial = _run(
        git_repo,
        turns=[_read_turn(0), LlmToolTurn(content="done", tool_calls=[])],
        sizes=[100, 120],
    )

    assert trial.completion_checks["context_compactions"] == 0
    assert trial.completion_checks["context_peak_prompt_tokens"] == 120


def test_v2_reports_no_context_metrics_at_all(git_repo):
    """Absent metrics mean "no context management", which is distinct from "it did nothing"."""
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="x", workspace_path=str(sandbox.root), max_steps=4, timeout_seconds=60
        )
        trial = MiniAgent(
            _StubProvider([LlmToolTurn(content="done", tool_calls=[])], [100]),
            AgentConfig.for_harness("v2"),
        ).run(task, sandbox)

    assert "context_compactions" not in trial.completion_checks


# --------------------------------------------------------------------------- #
# Ablation
# --------------------------------------------------------------------------- #
def test_each_v3_addition_can_be_removed_on_its_own(git_repo):
    """An ablation has to isolate one capability, or a V2/V3 delta cannot be attributed."""
    task = AgentTask(instruction="x", workspace_path="", max_steps=3, timeout_seconds=30)

    for ablate, expect_context in ((frozenset(), True), (frozenset({"context"}), False)):
        adapter = MiniAgentAdapter(
            _StubProvider([LlmToolTurn(content="x", tool_calls=[])], [100]),
            harness="v3",
            ablate=ablate,
            context_budget_tokens=1000,
        )
        with WorktreeSandbox(git_repo) as sandbox:
            adapter.prepare(sandbox.root, task, BudgetContract(max_wall_clock_s=30), runtime=sandbox)
            result = adapter.run("x")
            adapter.cleanup()

        assert ("context_compactions" in result.completion_checks) is expect_context
        assert result.env_manifest["ablate"] == sorted(ablate)


# --------------------------------------------------------------------------- #
# The ceiling: a constraint that binds on every arm
# --------------------------------------------------------------------------- #
def _ceiling_run(git_repo, *, ceiling, context_management, sizes):
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=8, timeout_seconds=60
        )
        config = AgentConfig.for_harness(
            "v3" if context_management else "v2",
            enable_context_management=context_management,
            context_budget_tokens=1000,
            context_ceiling_tokens=ceiling,
        )
        turns = [_read_turn(n) for n in range(6)] + [LlmToolTurn(content="done", tool_calls=[])]
        return MiniAgent(_StubProvider(turns, sizes), config).run(task, sandbox)


def test_exceeding_the_ceiling_stops_the_trial_for_every_harness(git_repo):
    """The ceiling stands in for a smaller model window, so it constrains V2 exactly as it
    constrains V3 — otherwise a V2/V3 comparison only measures compaction's cost."""
    trial = _ceiling_run(git_repo, ceiling=1000, context_management=False, sizes=[100, 1500])

    assert trial.stop_reason == "context_overflow"
    assert trial.completion_checks["context_overflowed"] is True
    assert trial.completion_checks["peak_prompt_tokens"] == 1500
    overflow = [e for e in trial.events if e.name == "context_overflow"]
    assert overflow and overflow[0].payload["ceiling"] == 1000


def test_work_done_before_an_overflow_is_kept(git_repo):
    """A real context exhaustion does not undo edits already written to the repository."""
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=6, timeout_seconds=60
        )
        turns = [
            LlmToolTurn(tool_calls=[LlmToolCall(
                call_id="e", name="apply_patch",
                arguments={"path": "app.py", "old_str": "return a - b  # bug: should be +",
                           "new_str": "return a + b"})]),
            _read_turn(1),
        ]
        trial = MiniAgent(
            _StubProvider(turns, [100, 9999]),
            AgentConfig.for_harness("v2", context_ceiling_tokens=1000),
        ).run(task, sandbox)

    assert trial.stop_reason == "context_overflow"
    assert "+    return a + b" in trial.patch


def test_a_trial_below_the_ceiling_is_unaffected(git_repo):
    trial = _ceiling_run(git_repo, ceiling=100_000, context_management=False,
                         sizes=[100, 200, 300, 400, 500, 600, 700])

    assert trial.stop_reason != "context_overflow"
    assert trial.completion_checks["context_overflowed"] is False


def test_an_overflow_is_attributed_to_the_context_window(git_repo):
    from codeagent_eval.benchmark import EvalCase
    from codeagent_eval.failure_taxonomy import CONTEXT_OVERFLOW, attribute_failure
    from codeagent_eval.graders.constraint_grader import ConstraintGrade
    from codeagent_eval.graders.patch_grader import PatchGrade
    from codeagent_eval.graders.pytest_run import PytestOutcome
    from codeagent_eval.graders.result import GradeResult
    from codeagent_eval.graders.test_grader import TestGrade

    trial = _ceiling_run(git_repo, ceiling=1000, context_management=False, sizes=[100, 1500])
    empty = PytestOutcome(node_ids=[], exit_code=None)
    grade = GradeResult.model_construct(
        case_id="c", task_success=False, strict_success=False,
        test=TestGrade.model_construct(target_passed=False, regression_passed=False,
                                       hidden_passed=False, target=empty, regression=empty,
                                       hidden=empty),
        constraint=ConstraintGrade.model_construct(forbidden_paths_touched=[]),
        patch=PatchGrade.model_construct(modified_tests=False),
    )

    attribution = attribute_failure(EvalCase(case_id="c", task_type="bugfix", instruction="x"),
                                    trial, grade)
    assert attribution.primary == CONTEXT_OVERFLOW


def test_the_adapter_accepts_a_token_ceiling_it_can_now_enforce(git_repo):
    """It used to raise UnsupportedCapability; refusing a limit you can enforce would push the
    experiment back to constraining only one arm."""
    adapter = MiniAgentAdapter(
        _StubProvider([_read_turn(0), LlmToolTurn(content="x", tool_calls=[])], [100, 5000]),
        harness="v2",
    )
    task = AgentTask(instruction="x", workspace_path="", max_steps=4, timeout_seconds=30)
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(
            sandbox.root, task, BudgetContract(max_wall_clock_s=30, max_tokens=1000), runtime=sandbox
        )
        result = adapter.run("x")
        adapter.cleanup()

    assert result.stop_reason == "budget_context"
    assert result.native_stop_reason == "context_overflow"
    assert result.env_manifest["context_ceiling_tokens"] == 1000
    assert result.to_trial_result().stop_reason == "context_overflow"


# --------------------------------------------------------------------------- #
# Pre-compaction pressure notice
# --------------------------------------------------------------------------- #
def _at(manager: ContextManager, tokens: int) -> None:
    manager.observe(tokens)


def test_no_notice_while_there_is_room():
    manager = ContextManager(budget_tokens=1000, warn_threshold=0.55)
    _at(manager, 400)
    assert manager.pressure_notice([]) is None


def test_the_notice_fires_before_compaction_not_after():
    """A warning that only arrives once the drop has happened cannot be acted on."""
    manager = ContextManager(budget_tokens=1000, warn_threshold=0.55, compaction_threshold=0.75)
    _at(manager, 600)
    notice = manager.pressure_notice([])
    assert notice is not None
    assert "will be compacted soon" in notice
    assert not manager.should_compact([])


def test_no_notice_once_compaction_is_already_due():
    """At that point the digest's own message is the accurate thing to say."""
    manager = ContextManager(budget_tokens=1000, warn_threshold=0.55, compaction_threshold=0.75)
    _at(manager, 800)
    assert manager.pressure_notice([]) is None


def test_the_notice_fires_once_per_approach():
    """Repeating it every step would spend the budget it exists to protect."""
    manager = ContextManager(budget_tokens=1000, warn_threshold=0.55)
    _at(manager, 600)
    assert manager.pressure_notice([]) is not None
    _at(manager, 650)
    assert manager.pressure_notice([]) is None
    assert manager.stats.pressure_notices == 1


def test_the_notice_re_arms_after_a_compaction():
    manager = ContextManager(budget_tokens=1000, warn_threshold=0.55, keep_recent_messages=2)
    _at(manager, 600)
    assert manager.pressure_notice([]) is not None

    messages = [{"role": "user", "content": "task"}] + [
        {"role": "assistant", "content": f"step {i}"} for i in range(6)
    ]
    manager.compact(messages, step=5, digest="did things")
    _at(manager, 600)
    assert manager.pressure_notice([]) is not None, "the next approach deserves its own warning"
    assert manager.stats.pressure_notices == 2


def test_a_warn_threshold_at_or_above_compaction_is_refused():
    """Such a warning could never fire before the drop, which is its only useful moment."""
    with pytest.raises(ValueError, match="warn_threshold"):
        ContextManager(budget_tokens=1000, warn_threshold=0.75, compaction_threshold=0.75)
