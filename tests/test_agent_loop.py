"""M1 acceptance: the MiniAgent loop drives tools end-to-end, records a full trajectory,
exports the fix as a git diff, and terminates safely on budget/timeout.

Uses a scripted provider (no API key) so the loop, trace recording, tool dispatch, and
patch export are verified deterministically. A real-LLM smoke test is gated on env below.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeagent_eval.agent import AgentConfig, MiniAgent
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.sandbox import WorktreeSandbox


class ScriptedProvider:
    """Duck-typed stand-in for LlmProvider: returns pre-baked tool turns in order."""

    def __init__(self, turns: list[LlmToolTurn]):
        self._turns = turns
        self._i = 0
        self.last_error: str | None = None

    def tool_completion(self, **kwargs) -> LlmToolTurn | None:  # noqa: ARG002
        if self._i >= len(self._turns):
            # Nothing scripted left → emit a final (no tool calls) so the loop stops cleanly.
            return LlmToolTurn(content="done", tool_calls=[])
        turn = self._turns[self._i]
        self._i += 1
        return turn


def _fix_bug_script() -> list[LlmToolTurn]:
    return [
        LlmToolTurn(tool_calls=[LlmToolCall(call_id="c1", name="read_file", arguments={"path": "app.py"})]),
        LlmToolTurn(
            tool_calls=[
                LlmToolCall(
                    call_id="c2",
                    name="apply_patch",
                    arguments={
                        "path": "app.py",
                        "old_str": "return a - b  # bug: should be +",
                        "new_str": "return a + b",
                    },
                )
            ]
        ),
        LlmToolTurn(tool_calls=[LlmToolCall(call_id="c3", name="run_command", arguments={"command": "pytest -q"})]),
        LlmToolTurn(content="Fixed the sign bug in add(); pytest passes.", tool_calls=[]),
    ]


def test_agent_fixes_bug_end_to_end(git_repo: Path):
    provider = ScriptedProvider(_fix_bug_script())
    agent = MiniAgent(provider, AgentConfig(version="v1"))
    task = AgentTask(instruction="add(a, b) returns a-b but should return a+b. Fix it.", workspace_path="")

    with WorktreeSandbox(git_repo) as sb:
        result = agent.run(task, sb, case_id="fix_add")

    assert result.stop_reason == "final"
    assert result.final_message and "Fixed" in result.final_message
    # The fix was actually applied and exported as a diff:
    assert "+    return a + b" in result.patch
    assert result.changed_files == ["app.py"]
    # Completion checks reflect a healthy trial:
    assert result.completion_checks["has_changes"] is True
    assert result.completion_checks["ran_tests"] is True
    assert result.completion_checks["last_test_passed"] is True
    assert result.completion_checks["triggered_forbidden"] is False
    # Every tool call is in the trace, plus specialized events:
    types = [e.type for e in result.events]
    assert TraceEventType.TOOL_CALL in types
    assert TraceEventType.FILE_WRITE in types
    assert TraceEventType.TEST_RESULT in types
    assert TraceEventType.FINAL_ANSWER in types
    assert result.tool_call_count == 3


def test_agent_stops_on_max_steps(git_repo: Path):
    # A provider that never finishes: keeps listing files forever.
    class Loopy:
        last_error = None

        def tool_completion(self, **kwargs):  # noqa: ARG002
            return LlmToolTurn(tool_calls=[LlmToolCall(call_id="x", name="list_files", arguments={"path": "."})])

    agent = MiniAgent(Loopy(), AgentConfig(version="v1"))
    task = AgentTask(instruction="loop", workspace_path="", max_steps=3)
    with WorktreeSandbox(git_repo) as sb:
        result = agent.run(task, sb)
    assert result.stop_reason == "max_steps"
    assert result.steps == 3
    assert result.completion_checks["over_steps"] is True


def test_provider_failure_is_contained(git_repo: Path):
    class Broken:
        last_error = "boom"

        def tool_completion(self, **kwargs):  # noqa: ARG002
            return None

    agent = MiniAgent(Broken(), AgentConfig(version="v1"))
    task = AgentTask(instruction="x", workspace_path="")
    with WorktreeSandbox(git_repo) as sb:
        result = agent.run(task, sb)
    assert result.stop_reason == "provider_error"
    assert result.completion_checks["provider_error"] is True


def test_v2_repeated_action_guard(git_repo: Path):
    class Repeater:
        last_error = None

        def tool_completion(self, **kwargs):  # noqa: ARG002
            return LlmToolTurn(
                tool_calls=[LlmToolCall(call_id="r", name="run_command", arguments={"command": "pytest -q"})]
            )

    agent = MiniAgent(Repeater(), AgentConfig(version="v2", detect_repeated_actions=True, repeated_action_limit=3))
    task = AgentTask(instruction="x", workspace_path="", max_steps=10)
    with WorktreeSandbox(git_repo) as sb:
        result = agent.run(task, sb)
    assert result.stop_reason == "repeated_action"


@pytest.mark.skipif(
    not (os.getenv("RUN_LLM_SMOKE") and (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))),
    reason="set RUN_LLM_SMOKE=1 and an API key to run the real-model smoke test",
)
def test_real_llm_smoke(git_repo: Path):
    from codeagent_eval.llm import LlmProvider
    from codeagent_eval.settings import load_settings

    provider = LlmProvider(load_settings())
    agent = MiniAgent(provider, AgentConfig(version="v1"))
    task = AgentTask(
        instruction="The function add(a, b) in app.py returns a-b but should return a+b. "
        "Fix it and run the tests.",
        workspace_path="",
        max_steps=12,
    )
    with WorktreeSandbox(git_repo) as sb:
        result = agent.run(task, sb)
    assert "+    return a + b" in result.patch
    assert result.completion_checks["last_test_passed"] is True
