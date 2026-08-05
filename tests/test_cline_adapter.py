"""W2-8: the second external framework, which is what makes the adapter protocol a claim.

One external adapter proves a wrapper works. Two prove the contract is a contract — and the
first thing adding Cline did was falsify a piece of it, since the canary detector's argument
vocabulary turned out to be Claude Code's rather than the protocol's (see
``test_context_amnesia``). These tests pin the parts of Cline that differ from Claude Code in
kind, not just in spelling:

* tool detail lives in a session file, not the stream, so a run whose session cannot be read
  must say so rather than present a short trajectory;
* the CLI computes cost from a price table that does not describe a third-party endpoint;
* resumed turns re-read the whole session, so concatenating would double the trajectory.

The fake ``cline`` stand-in is a real subprocess, so streaming, wall-clock enforcement and
environment scrubbing run for real.
"""

from __future__ import annotations

import json

import pytest

from codeagent_eval.adapters import (
    BudgetContract,
    Capability,
    ClineAdapter,
    ClineConfig,
    UnsupportedCapability,
    create_adapter,
)
from codeagent_eval.adapters.cline import (
    CLINE_SEMANTICS,
    ParsedSession,
    collect_session_events,
    parse_session_file,
    parse_stream,
)
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.sandbox import WorktreeSandbox


# --------------------------------------------------------------------------- #
# Session-store record builders (shapes copied from a real Cline run)
# --------------------------------------------------------------------------- #
def assistant(*blocks, model: str = "glm-5.2") -> dict:
    return {"role": "assistant", "content": list(blocks), "modelInfo": {"id": model}}


def tool_use(name: str, **inputs) -> dict:
    return {"type": "tool_use", "id": f"call_{name}", "name": name, "input": inputs}


def session_document(*messages, session_id: str = "sess-1") -> dict:
    return {"version": 1, "sessionId": session_id, "messages": list(messages)}


def run_result(**over) -> dict:
    return {
        "type": "run_result",
        "finishReason": "completed",
        "iterations": 4,
        "durationMs": 12_000,
        "aggregateUsage": {
            "inputTokens": 28_845,
            "outputTokens": 886,
            "cacheReadTokens": 23_258,
            "totalCost": 0.42,
        },
        **over,
    }


# --------------------------------------------------------------------------- #
# Tool semantics
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("tool", "command", "expected"),
    [
        ("read_files", None, TraceEventType.FILE_READ),
        ("editor", None, TraceEventType.FILE_WRITE),
        ("run_commands", "ls -la", TraceEventType.COMMAND_FINISH),
        ("run_commands", "pytest -q", TraceEventType.TEST_RESULT),
        ("update_todo_list", None, TraceEventType.PLAN_UPDATE),
    ],
)
def test_cline_tools_map_onto_shared_semantics(tool, command, expected):
    assert CLINE_SEMANTICS.classify(tool, command=command) is expected


def test_an_unknown_tool_is_recorded_rather_than_guessed():
    """A future Cline release adding a tool must not silently vanish from the trajectory."""
    assert CLINE_SEMANTICS.classify("browser_action") is TraceEventType.TOOL_RESULT
    assert not CLINE_SEMANTICS.knows("browser_action")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def test_stream_supplies_run_level_facts():
    summary = parse_stream([
        {"type": "hook_event", "hookEventName": "tool_call", "taskId": "conv-9"},
        {"type": "agent_event", "event": {"type": "usage", "inputTokens": 5}},
        run_result(),
    ])

    assert summary["finish_reason"] == "completed"
    assert (summary["prompt_tokens"], summary["completion_tokens"]) == (28_845, 886)
    assert summary["cached_tokens"] == 23_258
    assert summary["session_id"] == "conv-9"
    assert summary["tool_calls"] == 1


def test_session_file_supplies_paths_and_commands_the_stream_cannot(tmp_path):
    """The whole reason the adapter reads the session store at all."""
    path = tmp_path / "s.messages.json"
    path.write_text(json.dumps(session_document(
        assistant(tool_use("read_files", files=[{"path": "/wt/mini_store/cart.py"}])),
        assistant(tool_use("editor", path="/wt/mini_store/cart.py", new_text="body")),
        assistant(tool_use("run_commands", commands=["pytest -q"])),
    )))
    parsed = ParsedSession()
    parse_session_file(path, parsed)

    calls = [e for e in parsed.events if e.type is TraceEventType.TOOL_CALL]
    assert [c.name for c in calls] == ["read_files", "editor", "run_commands"]
    assert calls[1].payload["path"] == "/wt/mini_store/cart.py"
    assert calls[2].payload["command"] == "pytest -q"
    assert calls[2].payload["is_test_command"] is True
    assert parsed.tool_calls == 3
    assert parsed.model_turns == 3


def test_the_served_model_is_recorded_not_the_requested_one():
    """An artifact naming a model that never answered is worse than one that fails loudly."""
    parsed = ParsedSession()
    document = session_document(assistant(tool_use("read_files", path="a.py"), model="glm-4.5-air"))
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "s.messages.json"
        file.write_text(json.dumps(document))
        parse_session_file(file, parsed)

    assert parsed.served_model == "glm-4.5-air"


def test_several_session_files_share_one_monotonic_step_axis(tmp_path):
    """A resumed run writes more than one file; overlapping steps would corrupt the ordering."""
    sessions = tmp_path / "sessions"
    for index, name in enumerate(("a", "b")):
        directory = sessions / name
        directory.mkdir(parents=True)
        (directory / f"{name}.messages.json").write_text(
            json.dumps(session_document(
                assistant(tool_use("editor", path=f"f{index}.py", new_text="x")),
                session_id=name,
            ))
        )
    parsed = ParsedSession()
    collect_session_events(tmp_path, parsed)

    steps = [e.step for e in parsed.events if e.type is TraceEventType.TOOL_CALL]
    assert steps == sorted(steps)
    assert len(set(steps)) == 2


def test_an_unreadable_session_is_counted_not_swallowed(tmp_path):
    """A short trajectory and an unread one are indistinguishable to every detector."""
    directory = tmp_path / "sessions" / "a"
    directory.mkdir(parents=True)
    (directory / "a.messages.json").write_text("{not json")

    parsed = ParsedSession()
    collect_session_events(tmp_path, parsed)

    assert parsed.unreadable_sessions == 1
    assert parsed.events == []


# --------------------------------------------------------------------------- #
# Adapter behaviour against the fake CLI
# --------------------------------------------------------------------------- #
def _config(fake_cline, **over) -> ClineConfig:
    return ClineConfig(
        cli_path=str(fake_cline.cli_path),
        model="glm-5.2",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        **over,
    )


def _task(sandbox=None, **over) -> AgentTask:
    return AgentTask(
        case_id="cline-case",
        instruction="fix it",
        workspace_path=str(sandbox.root) if sandbox is not None else "",
        max_steps=10,
        timeout_seconds=60,
        **over,
    )


def test_probe_reports_the_installed_version(fake_cline):
    probe = ClineAdapter(_config(fake_cline)).probe()
    assert probe.available is True
    assert probe.version == "3.0.49"


def test_a_missing_binary_is_unavailable_rather_than_an_exception(tmp_path):
    probe = ClineAdapter(ClineConfig(cli_path=str(tmp_path / "absent"))).probe()
    assert probe.available is False
    assert "not found" in (probe.detail or "")


def test_the_registry_rejects_a_config_for_the_wrong_adapter():
    with pytest.raises(TypeError, match="ClineConfig"):
        create_adapter("cline", config=object())


def test_capabilities_exclude_native_cost(fake_cline):
    caps = ClineAdapter(_config(fake_cline)).capabilities()
    assert Capability.MULTI_TURN in caps
    assert Capability.NATIVE_COST not in caps


def test_a_context_ceiling_is_refused_rather_than_ignored(git_repo, fake_cline):
    """Silently accepting a budget the framework cannot enforce makes arms incomparable."""
    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox, pytest.raises(UnsupportedCapability):
        adapter.prepare(
            sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=30, max_tokens=8000),
            runtime=sandbox,
        )


def test_a_run_reports_cost_as_unavailable_despite_the_cli_naming_a_number(git_repo, fake_cline):
    """The CLI's price table does not describe a third-party OpenAI-compatible endpoint."""
    fake_cline.script(
        lines=[json.dumps(run_result())],
        messages=[assistant(tool_use("editor", path="app.py", new_text="def add(a,b): return a+b"))],
        edits={"app.py": "def add(a, b):\n    return a + b\n"},
    )
    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=30), runtime=sandbox)
        try:
            result = adapter.run("fix it")
        finally:
            adapter.cleanup()

    assert result.cost_usd is None
    assert result.cost_source == "unavailable"
    assert result.env_manifest["native_cost_usd_untrusted"] == 0.42
    assert result.stop_reason == "final"
    assert result.tool_call_count == 1


def test_the_child_environment_is_scrubbed_to_the_allowlist(git_repo, fake_cline, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    fake_cline.script(lines=[json.dumps(run_result())], messages=[])

    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=30), runtime=sandbox)
        try:
            adapter.run("fix it")
        finally:
            adapter.cleanup()

    child_env = fake_cline.invocation()["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in child_env
    assert child_env.get("PYTHONDONTWRITEBYTECODE") == "1"


def test_a_hanging_run_is_killed_at_the_wall_clock(git_repo, fake_cline):
    fake_cline.script(lines=[json.dumps(run_result())], messages=[], sleep_s=30)
    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=2), runtime=sandbox)
        try:
            result = adapter.run("fix it")
        finally:
            adapter.cleanup()

    assert result.stop_reason == "budget_time"
    assert result.native_stop_reason == "harness_wall_clock_kill"
    assert result.native_trajectory_path, "a killed trial must still leave its raw stream"


def test_a_run_whose_session_cannot_be_read_is_flagged(git_repo, fake_cline):
    """Tool calls seen on the stream but absent from the store mean the trajectory is partial."""
    fake_cline.script(
        lines=[
            json.dumps({"type": "hook_event", "hookEventName": "tool_call", "taskId": "c1"}),
            json.dumps(run_result()),
        ],
        messages=None,  # no session file written at all
    )
    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=30), runtime=sandbox)
        try:
            result = adapter.run("fix it")
        finally:
            adapter.cleanup()

    assert result.completion_checks["trajectory_incomplete"] is True


def test_auth_failure_is_raised_before_any_trial_time_is_spent(git_repo, fake_cline):
    fake_cline.script(auth_exit_code=3)
    adapter = ClineAdapter(_config(fake_cline))
    with WorktreeSandbox(git_repo) as sandbox, pytest.raises(UnsupportedCapability, match="auth"):
        adapter.prepare(sandbox.root, _task(sandbox), BudgetContract(max_wall_clock_s=30), runtime=sandbox)
