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


def test_limits_are_per_tool():
    """Reading a file is worth more context than listing a directory."""
    mgr = manager()
    long_text = "y" * 20_000

    assert len(mgr.truncate_tool_output("read_file", long_text)) < 6100
    assert len(mgr.truncate_tool_output("list_files", long_text)) < 2100
    assert len(mgr.truncate_tool_output("read_file", long_text)) > len(
        mgr.truncate_tool_output("list_files", long_text)
    )


def test_an_unknown_tool_falls_back_to_the_default_limit():
    assert len(manager().truncate_tool_output("some_new_tool", "z" * 9999)) <= (
        DEFAULT_TOOL_OUTPUT_LIMIT + 100
    )


def test_truncation_is_counted_for_the_trial_record():
    mgr = manager()
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
    return LlmToolTurn(
        tool_calls=[LlmToolCall(call_id=f"r{n}", name="read_file", arguments={"path": "app.py"})]
    )


def _run(git_repo, *, turns, sizes, **config_over):
    with WorktreeSandbox(git_repo) as sandbox:
        task = AgentTask(
            instruction="fix add", workspace_path=str(sandbox.root), max_steps=12, timeout_seconds=60
        )
        config = AgentConfig(
            version="v3", enable_context_management=True, context_budget_tokens=1000, **config_over
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
            AgentConfig(version="v2"),
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
