"""W1-3: Claude Code headless adapter — stream-json normalization and run contract.

The parser tests run against recorded stream-json records; the adapter tests drive a real
``claude`` stand-in subprocess (see ``tests/fake_claude.py``) so streaming, wall-clock
enforcement, process-group termination and environment scrubbing are exercised rather than
mocked. Live verification against an installed CLI is tracked separately — these tests pin
the contract, not the vendor's schema.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from codeagent_eval.adapters import (
    CLAUDE_CODE_SEMANTICS,
    BudgetContract,
    Capability,
    ClaudeCodeAdapter,
    ClaudeCodeConfig,
    UnsupportedCapability,
    create_adapter,
    is_test_command,
    parse_stream_json,
)
from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import EvalCase
from codeagent_eval.failure_taxonomy import attribute_failure, canonical_stop_reason
from codeagent_eval.graders.constraint_grader import ConstraintGrade
from codeagent_eval.graders.patch_grader import PatchGrade
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.graders.test_grader import TestGrade
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.runner import (
    _is_infra_invalid,
    _relocate_native_trajectory,
    _resolve_agent_kind,
)
from codeagent_eval.sandbox import WorktreeSandbox

FIXED_APP = "def add(a, b):\n    return a + b\n"


# --------------------------------------------------------------------------- #
# stream-json record builders
# --------------------------------------------------------------------------- #
def init_record(**over) -> dict:
    return {
        "type": "system",
        "subtype": "init",
        "session_id": "sess-1",
        "model": "claude-opus-5",
        "tools": ["Read", "Edit", "Bash", "TodoWrite"],
        **over,
    }


def assistant_record(*, text=None, tools=(), usage=None) -> dict:
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for tool_id, name, args in tools:
        content.append({"type": "tool_use", "id": tool_id, "name": name, "input": args})
    message = {"role": "assistant", "content": content, "stop_reason": "tool_use"}
    if usage:
        message["usage"] = usage
    return {"type": "assistant", "message": message, "session_id": "sess-1"}


def tool_result_record(tool_id: str, content: str, *, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
        "session_id": "sess-1",
    }


def result_record(*, subtype="success", is_error=False, cost=0.0731, usage=None, turns=4) -> dict:
    return {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "duration_ms": 12345,
        "num_turns": turns,
        "result": "Fixed the sign in add().",
        "total_cost_usd": cost,
        "usage": usage
        if usage is not None
        else {"input_tokens": 4210, "output_tokens": 318, "cache_read_input_tokens": 2048},
        "session_id": "sess-1",
    }


def full_session() -> list[dict]:
    return [
        init_record(),
        assistant_record(text="Reading the file.", tools=[("t1", "Read", {"file_path": "app.py"})]),
        tool_result_record("t1", "def add(a, b):\n    return a - b\n"),
        assistant_record(tools=[("t2", "Edit", {"file_path": "app.py", "new_string": "a + b"})]),
        tool_result_record("t2", "edited"),
        assistant_record(tools=[("t3", "Bash", {"command": "python -m pytest -q"})]),
        tool_result_record("t3", "1 passed"),
        assistant_record(tools=[("t4", "TodoWrite", {"todos": [{"content": "fix", "status": "completed"}]})]),
        tool_result_record("t4", "ok"),
        assistant_record(text="Done."),
        result_record(),
    ]


# --------------------------------------------------------------------------- #
# Pure parser
# --------------------------------------------------------------------------- #
def test_parse_normalizes_a_full_session_into_trace_semantics():
    parsed = parse_stream_json(full_session())

    assert parsed.model_turns == 5
    assert parsed.tool_calls == 4
    assert parsed.session_id == "sess-1"
    assert parsed.model == "claude-opus-5"
    assert parsed.tools_offered == ["Read", "Edit", "Bash", "TodoWrite"]
    assert parsed.final_message == "Fixed the sign in add()."
    assert parsed.result_subtype == "success"
    assert parsed.ran_tests is True
    assert parsed.last_test_ok is True

    kinds = [e.type for e in parsed.events]
    assert kinds.count(TraceEventType.MODEL_RESPONSE) == 5
    assert kinds.count(TraceEventType.TOOL_CALL) == 4
    assert TraceEventType.FILE_READ in kinds
    assert TraceEventType.FILE_WRITE in kinds
    assert TraceEventType.TEST_RESULT in kinds
    assert TraceEventType.PLAN_UPDATE in kinds
    assert kinds[-1] is TraceEventType.FINAL_ANSWER

    read_event = next(e for e in parsed.events if e.type is TraceEventType.FILE_READ)
    assert read_event.payload["path"] == "app.py"
    assert read_event.step == 1  # attributed to the turn that issued the tool_use


def test_result_usage_supersedes_per_turn_usage():
    """Per-turn usage double-counts prompt tokens (context is resent each turn), so the
    authoritative result record must replace it rather than add to it."""
    records = [
        assistant_record(text="a", usage={"input_tokens": 1000, "output_tokens": 50}),
        assistant_record(text="b", usage={"input_tokens": 1800, "output_tokens": 40}),
        result_record(usage={"input_tokens": 1800, "output_tokens": 90, "cache_read_input_tokens": 12}),
    ]
    parsed = parse_stream_json(records)

    assert parsed.prompt_tokens == 1800
    assert parsed.completion_tokens == 90
    assert parsed.cached_tokens == 12
    assert parsed.usage_source == "result"


def test_missing_result_falls_back_to_turn_usage_and_flags_provenance():
    parsed = parse_stream_json(
        [assistant_record(text="a", usage={"input_tokens": 1000, "output_tokens": 50})]
    )

    assert parsed.saw_result is False
    assert parsed.prompt_tokens == 1000
    assert parsed.usage_source == "assistant_turns"


def test_unknown_records_and_blocks_are_counted_not_fatal():
    """A CLI upgrade must degrade the trace, never abort a trial that already spent budget."""
    records = [
        {"type": "stream_event", "event": {"type": "content_block_delta"}},
        {"type": "stream_event", "event": {}},
        assistant_record(text="hi", tools=[("t1", "WebFetch", {"url": "https://x"})]),
        tool_result_record("t1", "fetched"),
        result_record(),
    ]
    parsed = parse_stream_json(records, malformed_lines=2)

    assert parsed.unknown_record_types == {"stream_event": 2}
    assert parsed.malformed_lines == 2
    unmapped = next(e for e in parsed.events if e.payload.get("unmapped_tool"))
    assert unmapped.type is TraceEventType.TOOL_RESULT


def test_command_exit_code_is_inferred_and_labelled_as_such():
    """stream-json reports success as a boolean. The derived exit code keeps shared aggregates
    computable, and the provenance key stops a reader treating it as a real exit status."""
    records = [
        assistant_record(tools=[("t1", "Bash", {"command": "pytest -q"})]),
        tool_result_record("t1", "1 failed", is_error=True),
        result_record(),
    ]
    parsed = parse_stream_json(records)

    test_event = next(e for e in parsed.events if e.type is TraceEventType.TEST_RESULT)
    assert test_event.payload["exit_code"] == 1
    assert test_event.payload["exit_code_source"] == "inferred_from_is_error"
    assert test_event.payload["command"] == "pytest -q"
    assert parsed.last_test_ok is False


def test_non_test_bash_is_a_command_not_a_test_run():
    records = [
        assistant_record(tools=[("t1", "Bash", {"command": "ls -la"})]),
        tool_result_record("t1", "app.py"),
    ]
    parsed = parse_stream_json(records)

    assert parsed.ran_tests is False
    assert any(e.type is TraceEventType.COMMAND_FINISH for e in parsed.events)


def test_error_result_becomes_an_error_event():
    parsed = parse_stream_json([result_record(subtype="error_during_execution", is_error=True)])

    assert parsed.is_error is True
    assert parsed.events[-1].type is TraceEventType.ERROR


# --------------------------------------------------------------------------- #
# Shared normalization vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("tool", "command", "expected"),
    [
        ("Read", None, TraceEventType.FILE_READ),
        ("Edit", None, TraceEventType.FILE_WRITE),
        ("MultiEdit", None, TraceEventType.FILE_WRITE),
        ("Write", None, TraceEventType.FILE_WRITE),
        ("Bash", "uv run pytest -k x", TraceEventType.TEST_RESULT),
        ("Bash", "git status", TraceEventType.COMMAND_FINISH),
        ("TodoWrite", None, TraceEventType.PLAN_UPDATE),
        ("Grep", None, TraceEventType.TOOL_RESULT),
    ],
)
def test_claude_semantics_classification(tool, command, expected):
    assert CLAUDE_CODE_SEMANTICS.classify(tool, command) is expected


def test_test_command_predicate_matches_mini_agent_semantics():
    """Guard against drift: the MiniAgent loop decides `TEST_RESULT` inline, and a
    cross-agent test-run comparison is meaningless if the two definitions diverge."""
    source = Path("src/codeagent_eval/agent/loop.py").read_text()
    assert 'command.strip().startswith("pytest") or "pytest" in command' in source
    for command in ("pytest -q", "python -m pytest", "uv run pytest tests", "ls", "git diff"):
        expected = command.strip().startswith("pytest") or "pytest" in command
        assert is_test_command(command) is expected


# --------------------------------------------------------------------------- #
# Adapter: probe
# --------------------------------------------------------------------------- #
def test_probe_reports_a_missing_cli_actionably(tmp_path):
    probe = ClaudeCodeAdapter(ClaudeCodeConfig(cli_path=str(tmp_path / "claude-absent"))).probe()

    assert probe.available is False
    assert probe.version == "unknown"
    assert "not found" in probe.detail


def test_probe_parses_version_from_the_cli(fake_claude, tmp_path):
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    probe = adapter.probe()

    assert probe.available is True
    assert probe.version == "1.2.3 (Claude Code)"
    assert adapter.adapter_version == "1.2.3 (Claude Code)"


def test_capabilities_declare_the_four_jd_named_abilities(fake_claude, tmp_path):
    caps = ClaudeCodeAdapter(_config(fake_claude, tmp_path)).capabilities()

    assert {
        Capability.PLANNING,
        Capability.MEMORY,
        Capability.COMPACTION,
        Capability.MULTI_TURN,
    } <= caps


# --------------------------------------------------------------------------- #
# Adapter: run contract
# --------------------------------------------------------------------------- #
def _config(fake_claude, tmp_path, **over) -> ClaudeCodeConfig:
    return ClaudeCodeConfig(
        cli_path=str(fake_claude.cli_path),
        native_log_dir=tmp_path / "native",
        **over,
    )


def _prepare(adapter, sandbox, *, wall_clock=30, max_steps=12) -> None:
    task = AgentTask(
        instruction="fix add",
        workspace_path=str(sandbox.root),
        case_id="adapter-case",
        max_steps=max_steps,
        timeout_seconds=wall_clock,
    )
    adapter.prepare(
        sandbox.root,
        task,
        BudgetContract(max_wall_clock_s=wall_clock, max_steps=max_steps),
        runtime=sandbox,
    )


def test_run_exports_patch_records_native_cost_and_retains_raw_trajectory(
    fake_claude, git_repo, tmp_path, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    fake_claude.script(
        lines=[json.dumps(r) for r in full_session()],
        edits={"app.py": FIXED_APP},
    )
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path, model="claude-opus-5"))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.adapter == "claude_code"
    assert result.adapter_version == "1.2.3 (Claude Code)"
    assert result.stop_reason == "final"
    assert result.native_stop_reason == "success"
    assert "+    return a + b" in result.patch
    assert result.changed_files == ["app.py"]
    assert result.steps == 5
    assert result.tool_call_count == 4
    assert result.cost_usd == pytest.approx(0.0731)
    assert result.cost_source == "native"
    assert result.prompt_tokens == 4210
    assert result.cached_tokens == 2048
    assert result.completion_checks["ran_tests"] is True
    assert result.completion_checks["command_policy_enforced"] is False
    assert result.env_manifest["model_reported"] == "claude-opus-5"
    assert result.env_manifest["repo_commit"]

    raw = Path(result.native_trajectory_path)
    assert raw.exists()
    assert len(raw.read_text().strip().splitlines()) == len(full_session())


def test_result_round_trips_into_the_grading_contract(fake_claude, git_repo, tmp_path):
    fake_claude.script(lines=[json.dumps(r) for r in full_session()], edits={"app.py": FIXED_APP})
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    trial = result.to_trial_result()
    assert trial.stop_reason == "success"          # native vocabulary preserved
    assert trial.canonical_stop_reason == "final"  # comparison vocabulary carried alongside
    assert canonical_stop_reason(trial) == "final"
    assert trial.prompt_tokens == result.prompt_tokens
    assert trial.completion_tokens == result.completion_tokens
    assert trial.total_tokens == result.total_tokens


def test_max_turns_exhaustion_maps_to_budget_steps(fake_claude, git_repo, tmp_path):
    fake_claude.script(
        lines=[json.dumps(init_record()), json.dumps(result_record(subtype="error_max_turns", is_error=True))]
    )
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.stop_reason == "budget_steps"
    assert result.native_stop_reason == "error_max_turns"


def test_missing_result_record_is_an_execution_error(fake_claude, git_repo, tmp_path):
    fake_claude.script(lines=[json.dumps(init_record())], exit_code=1, stderr="boom\n")
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.stop_reason == "error"
    assert "no_result_record(exit=1)" == result.native_stop_reason
    assert result.env_manifest["stderr_bytes"] > 0
    assert Path(result.native_trajectory_path).with_suffix(".stderr.log").exists()


def test_wall_clock_budget_kills_the_process_group_and_keeps_partial_trajectory(
    fake_claude, git_repo, tmp_path
):
    marker = tmp_path / "child-survived.txt"
    fake_claude.script(
        lines=[json.dumps(init_record()), json.dumps(assistant_record(text="working"))],
        sleep_s=60,
        spawn_child={"marker": str(marker), "delay_s": 3},
    )
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox, wall_clock=1)
        started = time.monotonic()
        result = adapter.run("fix add")
        elapsed = time.monotonic() - started
        adapter.cleanup()

    assert result.stop_reason == "budget_time"
    assert result.native_stop_reason == "wall_clock_timeout"
    assert elapsed < 30, "the budget must terminate the run, not wait for the CLI"
    # The partial trajectory is what explains a budget kill, so it must already be durable.
    assert len(Path(result.native_trajectory_path).read_text().strip().splitlines()) == 2
    assert result.steps == 1

    time.sleep(4)
    assert not marker.exists(), "a tool spawned by the CLI outlived the process-group kill"


def test_malformed_stream_lines_are_tolerated_and_surfaced(fake_claude, git_repo, tmp_path):
    fake_claude.script(
        lines=["not json at all", "[1,2,3]", json.dumps(init_record()), json.dumps(result_record())]
    )
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.stop_reason == "final"
    assert result.env_manifest["malformed_stream_lines"] == 2


# --------------------------------------------------------------------------- #
# Adapter: invocation, isolation, cost provenance
# --------------------------------------------------------------------------- #
def test_argv_carries_the_budget_and_model(fake_claude, git_repo, tmp_path):
    fake_claude.script(lines=[json.dumps(result_record())])
    config = _config(fake_claude, tmp_path, model="glm-4.6", extra_args=("--fallback-model", "x"))
    adapter = ClaudeCodeAdapter(config)
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox, max_steps=7)
        adapter.run("fix add")
        adapter.cleanup()

    argv = fake_claude.invocation()["argv"]
    assert argv[:2] == ["-p", "fix add"]
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert argv[argv.index("--max-turns") + 1] == "7"
    assert argv[argv.index("--model") + 1] == "glm-4.6"
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[-2:] == ["--fallback-model", "x"]


def test_child_env_is_allowlisted_and_the_config_dir_is_isolated(
    fake_claude, git_repo, tmp_path, monkeypatch
):
    """The operator's real ~/.claude (settings, hooks, MCP servers, personal CLAUDE.md) would
    otherwise silently participate in every trial and make results machine-specific."""
    monkeypatch.setenv("ALGORA_SECRET", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_claude.script(lines=[json.dumps(result_record())])
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        config_dir = adapter._config_dir
        adapter.cleanup()

    env = fake_claude.invocation()["env"]
    assert "ALGORA_SECRET" not in env
    assert env["ANTHROPIC_API_KEY"] == "sk-test"  # provider credentials still reach the CLI
    assert env["CLAUDE_CONFIG_DIR"] == str(config_dir)
    assert Path(env["CLAUDE_CONFIG_DIR"]) != Path.home() / ".claude"
    assert result.env_manifest["config_isolated"] is True
    assert result.env_manifest["reproducible_config"] is True
    assert not config_dir.exists(), "cleanup must not leave per-trial config dirs behind"


def test_operator_config_mode_is_recorded_as_non_reproducible(fake_claude, git_repo, tmp_path):
    fake_claude.script(lines=[json.dumps(result_record())])
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path, isolate_config=False))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert "CLAUDE_CONFIG_DIR" not in fake_claude.invocation()["env"]
    assert result.env_manifest["reproducible_config"] is False


def test_third_party_endpoint_demotes_native_cost(fake_claude, git_repo, tmp_path, monkeypatch):
    """total_cost_usd is computed against Anthropic's price list; against another endpoint the
    number is arithmetically fine and semantically wrong, so it must not be reported."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
    fake_claude.script(lines=[json.dumps(r) for r in full_session()])
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.cost_usd is None
    assert result.cost_source == "unavailable"
    assert result.env_manifest["native_cost_trusted"] is False
    assert Capability.NATIVE_COST not in adapter.capabilities()
    # Tokens are still endpoint-independent and stay reportable.
    assert result.prompt_tokens == 4210


def test_harness_authored_scaffolding_is_stripped_before_the_patch(fake_claude, git_repo, tmp_path):
    """`.claude/` written by the CLI is harness residue, not the agent's work; leaving it in the
    diff would make patch-size and changed-file comparisons incommensurable across adapters."""
    fake_claude.script(
        lines=[json.dumps(result_record())],
        edits={"app.py": FIXED_APP, ".claude/settings.local.json": "{}"},
    )
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    assert result.changed_files == ["app.py"]
    assert ".claude" not in result.patch
    assert result.env_manifest["removed_harness_artifacts"] == [".claude"]


# --------------------------------------------------------------------------- #
# Adapter: lifecycle and budget enforcement
# --------------------------------------------------------------------------- #
def test_prepare_rejects_budgets_the_cli_cannot_enforce(fake_claude, git_repo, tmp_path):
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    task = AgentTask(instruction="x", workspace_path="", max_steps=3, timeout_seconds=10)
    with WorktreeSandbox(git_repo) as sandbox:
        with pytest.raises(UnsupportedCapability, match="cost ceiling"):
            adapter.prepare(
                sandbox.root, task, BudgetContract(max_wall_clock_s=10, max_cost_usd=1.0), runtime=sandbox
            )
        with pytest.raises(UnsupportedCapability, match="token ceiling"):
            adapter.prepare(
                sandbox.root, task, BudgetContract(max_wall_clock_s=10, max_tokens=1000), runtime=sandbox
            )
        with pytest.raises(TypeError, match="WorktreeSandbox"):
            adapter.prepare(sandbox.root, task, BudgetContract(max_wall_clock_s=10), runtime=None)


def test_run_before_prepare_is_a_programming_error(fake_claude, tmp_path):
    with pytest.raises(RuntimeError, match="prepared"):
        ClaudeCodeAdapter(_config(fake_claude, tmp_path)).run("x")


def test_run_against_an_absent_cli_refuses_instead_of_scoring_zero(git_repo, tmp_path):
    """An unavailable binary must never be gradeable as an agent failure."""
    adapter = ClaudeCodeAdapter(ClaudeCodeConfig(cli_path=str(tmp_path / "claude-absent")))
    task = AgentTask(instruction="x", workspace_path="", max_steps=3, timeout_seconds=10)
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, task, BudgetContract(max_wall_clock_s=10), runtime=sandbox)
        with pytest.raises(UnsupportedCapability, match="not found"):
            adapter.run("x")
        adapter.cleanup()


def test_continue_requires_a_session_then_resumes_it(fake_claude, git_repo, tmp_path):
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        with pytest.raises(UnsupportedCapability, match="no Claude Code session"):
            adapter.continue_("try again")

        fake_claude.script(lines=[json.dumps(init_record()), json.dumps(result_record())])
        adapter.run("fix add")
        adapter.continue_("tests still fail")
        adapter.cleanup()

    argv = fake_claude.invocation()["argv"]
    assert argv[argv.index("--resume") + 1] == "sess-1"


# --------------------------------------------------------------------------- #
# Registry + runner wiring
# --------------------------------------------------------------------------- #
def test_registry_builds_the_adapter_and_rejects_a_mismatched_config():
    assert isinstance(create_adapter("claude_code"), ClaudeCodeAdapter)
    assert create_adapter("claude_code", config=ClaudeCodeConfig(model="m")).config.model == "m"
    with pytest.raises(TypeError, match="ClaudeCodeConfig"):
        create_adapter("claude_code", config={"model": "m"})
    with pytest.raises(ValueError, match="no adapter config"):
        create_adapter("mini_agent", provider=None, config=ClaudeCodeConfig())


def test_native_trajectory_is_relocated_into_the_trial_directory(fake_claude, git_repo, tmp_path):
    """A trial directory is the unit that gets archived and turned into a repro bundle, so a
    pointer into a shared staging directory breaks as soon as that directory is cleaned."""
    fake_claude.script(lines=[json.dumps(init_record())], exit_code=1, stderr="boom\n")
    adapter = ClaudeCodeAdapter(_config(fake_claude, tmp_path))
    with WorktreeSandbox(git_repo) as sandbox:
        _prepare(adapter, sandbox)
        result = adapter.run("fix add")
        adapter.cleanup()

    staged = Path(result.native_trajectory_path)
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir()
    relocated = _relocate_native_trajectory(result, trial_dir)

    moved = Path(relocated.native_trajectory_path)
    assert moved.parent == trial_dir / "native"
    assert moved.exists() and not staged.exists()
    assert (trial_dir / "native" / staged.with_suffix(".stderr.log").name).exists()
    # Idempotent: re-persisting an artifact whose trajectory already moved must not raise.
    assert _relocate_native_trajectory(relocated, trial_dir).native_trajectory_path == str(moved)


def test_external_adapter_becomes_its_own_agent_label():
    """mini_agent folds into the V1/V2 harness axis; an external framework is its own system."""
    assert _resolve_agent_kind(None, "claude_code", "v2") == "claude_code"
    assert _resolve_agent_kind(None, "mini_agent", "v2") == "v2"


def _failed_grade() -> GradeResult:
    """A minimal failing grade carrying only the fields the taxonomy rules read."""
    return GradeResult.model_construct(
        case_id="c",
        task_success=False,
        strict_success=False,
        test=TestGrade.model_construct(
            target_passed=False, regression_passed=False, hidden_passed=False
        ),
        constraint=ConstraintGrade.model_construct(forbidden_paths_touched=[]),
        patch=PatchGrade.model_construct(modified_tests=False),
    )


def test_external_stop_reasons_attribute_through_canonical_semantics():
    """Pattern-matching native strings would silently mis-tag every external agent's failures."""
    case = EvalCase(case_id="c", task_type="bugfix", instruction="x")
    grade = _failed_grade()

    timed_out = TrialResult(stop_reason="wall_clock_timeout", canonical_stop_reason="budget_time")
    assert attribute_failure(case, timed_out, grade).primary == "TIMEOUT"

    out_of_turns = TrialResult(stop_reason="error_max_turns", canonical_stop_reason="budget_steps")
    assert attribute_failure(case, out_of_turns, grade).primary == "PLANNING"

    crashed = TrialResult(stop_reason="no_result_record(exit=1)", canonical_stop_reason="error")
    assert attribute_failure(case, crashed, grade).primary == "ENVIRONMENT"
    assert _is_infra_invalid(crashed) is True


def test_legacy_artifacts_without_canonical_reason_attribute_unchanged():
    case = EvalCase(case_id="c", task_type="bugfix", instruction="x")
    grade = _failed_grade()

    for native, expected in [
        ("timeout", "TIMEOUT"),
        ("max_steps", "PLANNING"),
        ("repeated_action", "REPEATED_ACTION"),
        ("provider_error", "ENVIRONMENT"),
    ]:
        assert attribute_failure(case, TrialResult(stop_reason=native), grade).primary == expected
