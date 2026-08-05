"""Adapter for Claude Code running headless, normalized into the V3 comparison contract.

Invocation shape::

    claude -p <instruction> --output-format stream-json --verbose \
           --max-turns <N> --model <model> --permission-mode <mode>

``stream-json`` emits newline-delimited JSON: a ``system/init`` record, then one
``assistant`` record per model turn (text + ``tool_use`` blocks), one ``user`` record per
batch of ``tool_result`` blocks, and a final ``result`` record carrying the authoritative
usage, cost and stop subtype.

Three properties this module treats as non-negotiable, because each one is a way an
external-agent comparison silently stops being valid:

1. **Config isolation.** The user's real ``~/.claude`` (settings, hooks, MCP servers,
   personal CLAUDE.md) would otherwise be read on every trial, making results
   unreproducible on any other machine. Each trial gets a private ``CLAUDE_CONFIG_DIR``.
2. **Cost provenance.** ``total_cost_usd`` is computed against Anthropic's price list. When
   the CLI is pointed at a third-party endpoint (``ANTHROPIC_BASE_URL``) the number is
   arithmetically fine but semantically wrong, so it is demoted to ``unavailable`` rather
   than reported as ``native``.
3. **Raw trajectory retention.** Records are appended to disk as they arrive, so a run
   killed by the wall-clock budget still leaves the partial trajectory that explains why.

Flag surface is deliberately minimal: only long-standing flags are emitted, and anything
version-specific goes through :attr:`ClaudeCodeConfig.extra_args` after being confirmed
against an installed CLI. ``probe()`` is the gate — no trial runs against an absent binary.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from codeagent_eval.adapters.base import (
    AgentRunResult,
    BudgetContract,
    CanonicalStopReason,
    Capability,
    ProbeResult,
    UnsupportedCapability,
)
from codeagent_eval.adapters.normalize import CLAUDE_CODE_SEMANTICS, is_test_command
from codeagent_eval.models import AgentTask, TraceEvent, TraceEventType, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

#: Endpoints for which ``total_cost_usd`` reflects the prices it was computed from.
TRUSTED_COST_ENDPOINT_PREFIXES = ("https://api.anthropic.com",)

#: Environment variables forwarded to the CLI verbatim, plus prefix families for the
#: provider backends (Anthropic direct, Bedrock, Vertex). Everything else is dropped so a
#: stray shell variable cannot change agent behavior between machines.
DEFAULT_ENV_ALLOWLIST = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "USER", "SHELL", "TERM"}
)
DEFAULT_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_", "AWS_", "GOOGLE_", "GCLOUD_", "CLOUD_ML_")

#: Written by the CLI itself rather than by the agent's work; removed before the patch is
#: exported so diffs stay comparable across adapters. Paths already tracked at the base
#: commit are never touched.
DEFAULT_HARNESS_ARTIFACTS = (".claude",)

_RESULT_SUBTYPE_STOP: dict[str, CanonicalStopReason] = {
    "success": "final",
    "error_max_turns": "budget_steps",
    "error_during_execution": "error",
}

_GRACE_PERIOD_S = 5.0


@dataclass(frozen=True)
class ClaudeCodeConfig:
    cli_path: str = "claude"
    model: str | None = None
    permission_mode: str = "bypassPermissions"
    extra_args: tuple[str, ...] = ()
    #: ``None`` auto-detects from ``ANTHROPIC_BASE_URL``; set explicitly to override.
    trust_native_cost: bool | None = None
    #: Disabling this lets trials read the operator's real Claude Code config. Required for
    #: OAuth-based auth, but the run is then not reproducible elsewhere — recorded either way.
    isolate_config: bool = True
    native_log_dir: Path = Path("artifacts/native_trajectories")
    harness_artifacts: tuple[str, ...] = DEFAULT_HARNESS_ARTIFACTS
    env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST
    env_prefixes: tuple[str, ...] = DEFAULT_ENV_PREFIXES
    probe_timeout_s: int = 30


@dataclass
class ParsedStream:
    """Everything recoverable from one stream-json run, before budget/patch interpretation."""

    events: list[TraceEvent] = field(default_factory=list)
    model_turns: int = 0
    tool_calls: int = 0
    final_message: str | None = None
    result_subtype: str | None = None
    is_error: bool = False
    saw_result: bool = False
    total_cost_usd: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    usage_source: str = "unavailable"
    session_id: str | None = None
    model: str | None = None
    tools_offered: list[str] = field(default_factory=list)
    ran_tests: bool = False
    last_test_ok: bool | None = None
    malformed_lines: int = 0
    unknown_record_types: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Stream parsing (pure: fully testable against recorded fixtures)
# --------------------------------------------------------------------------- #
def parse_stream_json(records: list[dict[str, Any]], *, malformed_lines: int = 0) -> ParsedStream:
    """Translate stream-json records into normalized trace events.

    Tolerant by construction: unknown record types and unknown content blocks are counted
    and skipped rather than raising, because a CLI upgrade must degrade the trace, never
    abort a trial that already spent real budget.
    """
    parsed = ParsedStream(malformed_lines=malformed_lines)
    pending_tools: dict[str, dict[str, Any]] = {}

    for record in records:
        rtype = record.get("type")
        if rtype == "system":
            _parse_system(record, parsed)
        elif rtype == "assistant":
            _parse_assistant(record, parsed, pending_tools)
        elif rtype == "user":
            _parse_user(record, parsed, pending_tools)
        elif rtype == "result":
            _parse_result(record, parsed)
        else:
            key = str(rtype)
            parsed.unknown_record_types[key] = parsed.unknown_record_types.get(key, 0) + 1

    if not parsed.saw_result and parsed.usage_source == "unavailable":
        # No authoritative result record (crash/timeout): fall back to per-turn usage, which
        # over-counts prompt tokens because each turn resends context. Flagged accordingly.
        parsed.usage_source = "assistant_turns" if parsed.prompt_tokens else "unavailable"
    return parsed


def _parse_system(record: dict[str, Any], parsed: ParsedStream) -> None:
    if record.get("subtype") != "init":
        return
    parsed.session_id = record.get("session_id") or parsed.session_id
    parsed.model = record.get("model") or parsed.model
    tools = record.get("tools")
    if isinstance(tools, list):
        parsed.tools_offered = [str(t) for t in tools]


def _parse_assistant(
    record: dict[str, Any], parsed: ParsedStream, pending_tools: dict[str, dict[str, Any]]
) -> None:
    message = record.get("message") or {}
    blocks = message.get("content")
    blocks = blocks if isinstance(blocks, list) else []
    parsed.model_turns += 1
    step = parsed.model_turns

    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    tool_uses = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]

    parsed.events.append(
        TraceEvent(
            step=step,
            type=TraceEventType.MODEL_RESPONSE,
            payload={
                "content": "\n".join(t for t in texts if t) or None,
                "tool_calls": len(tool_uses),
                "stop_reason": message.get("stop_reason"),
            },
        )
    )

    # Per-turn usage is only a fallback; ``result`` supersedes it when present.
    usage = message.get("usage")
    if isinstance(usage, dict) and not parsed.saw_result:
        parsed.prompt_tokens += _as_int(usage.get("input_tokens"))
        parsed.completion_tokens += _as_int(usage.get("output_tokens"))
        parsed.cached_tokens += _as_int(usage.get("cache_read_input_tokens"))

    for block in tool_uses:
        tool_id = str(block.get("id") or f"anon-{uuid4().hex[:8]}")
        name = str(block.get("name") or "unknown")
        arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
        pending_tools[tool_id] = {"name": name, "arguments": arguments, "step": step}
        parsed.tool_calls += 1
        parsed.events.append(
            TraceEvent(
                step=step,
                type=TraceEventType.TOOL_CALL,
                name=name,
                payload={"arguments": arguments, "tool_use_id": tool_id},
            )
        )


def _parse_user(
    record: dict[str, Any], parsed: ParsedStream, pending_tools: dict[str, dict[str, Any]]
) -> None:
    message = record.get("message") or {}
    blocks = message.get("content")
    blocks = blocks if isinstance(blocks, list) else []

    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_id = str(block.get("tool_use_id") or "")
        call = pending_tools.pop(tool_id, {"name": "unknown", "arguments": {}, "step": parsed.model_turns})
        name = str(call["name"])
        arguments: dict[str, Any] = call["arguments"]
        is_error = bool(block.get("is_error"))
        command = str(arguments.get("command", "")) if isinstance(arguments, dict) else ""
        event_type = CLAUDE_CODE_SEMANTICS.classify(name, command or None)

        payload: dict[str, Any] = {
            "ok": not is_error,
            "is_error": is_error,
            "tool_use_id": tool_id or None,
            "content": _summarize_tool_result(block.get("content")),
        }
        if event_type in (TraceEventType.COMMAND_FINISH, TraceEventType.TEST_RESULT):
            # stream-json reports success as a boolean, not an exit status. Deriving one keeps
            # the shared aggregates (failed_test_runs) computable; the provenance key records
            # that it is inferred, so no downstream reader mistakes it for a real exit code.
            payload["exit_code"] = 1 if is_error else 0
            payload["exit_code_source"] = "inferred_from_is_error"
            payload["command"] = command or None
        if event_type is TraceEventType.TEST_RESULT:
            parsed.ran_tests = True
            parsed.last_test_ok = not is_error
        if event_type in (TraceEventType.FILE_READ, TraceEventType.FILE_WRITE):
            payload["path"] = arguments.get("file_path") or arguments.get("path")
        if event_type is TraceEventType.PLAN_UPDATE:
            payload["plan"] = arguments.get("todos") or arguments.get("plan")
        if not CLAUDE_CODE_SEMANTICS.knows(name):
            payload["unmapped_tool"] = True

        parsed.events.append(
            TraceEvent(
                step=int(call["step"]),
                type=event_type,
                name=command or name,
                payload=payload,
            )
        )


def _parse_result(record: dict[str, Any], parsed: ParsedStream) -> None:
    parsed.saw_result = True
    parsed.result_subtype = record.get("subtype")
    parsed.is_error = bool(record.get("is_error"))
    parsed.session_id = record.get("session_id") or parsed.session_id
    result_text = record.get("result")
    parsed.final_message = result_text if isinstance(result_text, str) else parsed.final_message

    cost = record.get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost >= 0:
        parsed.total_cost_usd = float(cost)

    usage = record.get("usage")
    if isinstance(usage, dict):
        # Authoritative: replaces anything accumulated from assistant turns.
        parsed.prompt_tokens = _as_int(usage.get("input_tokens"))
        parsed.completion_tokens = _as_int(usage.get("output_tokens"))
        parsed.cached_tokens = _as_int(usage.get("cache_read_input_tokens"))
        parsed.usage_source = "result"

    parsed.events.append(
        TraceEvent(
            step=parsed.model_turns,
            type=TraceEventType.ERROR if parsed.is_error else TraceEventType.FINAL_ANSWER,
            name=parsed.result_subtype,
            payload={
                "content": parsed.final_message,
                "subtype": parsed.result_subtype,
                "num_turns": record.get("num_turns"),
                "duration_ms": record.get("duration_ms"),
            },
        )
    )


def _summarize_tool_result(content: Any, limit: int = 2000) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p) or json.dumps(content)[:limit]
    else:
        text = json.dumps(content)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[{len(text) - limit} chars truncated]…"


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


# --------------------------------------------------------------------------- #
# Subprocess streaming with a hard wall-clock deadline
# --------------------------------------------------------------------------- #
@dataclass
class _ProcessOutcome:
    records: list[dict[str, Any]]
    malformed_lines: int
    stderr: str
    returncode: int | None
    timed_out: bool
    launch_error: str | None = None


def _stream_process(
    argv: list[str], *, cwd: Path, env: dict[str, str], deadline_s: float, raw_log: Path,
    append: bool = False,
) -> _ProcessOutcome:
    """Run the CLI, persisting every stdout line to ``raw_log`` as it arrives.

    Writing through to disk during the run (rather than after) is what makes a
    budget-killed trial diagnosable: the partial trajectory is already durable when the
    process group is terminated.
    """
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    malformed = 0
    stderr_chunks: list[str] = []

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return _ProcessOutcome([], 0, "", None, False, launch_error=str(exc))

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)

    def drain_stdout(sink) -> None:
        nonlocal malformed
        assert proc.stdout is not None
        for line in proc.stdout:
            sink.write(line if line.endswith("\n") else line + "\n")
            sink.flush()
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(payload, dict):
                records.append(payload)
            else:
                malformed += 1

    with raw_log.open("a" if append else "w", encoding="utf-8") as sink:
        out_thread = threading.Thread(target=drain_stdout, args=(sink,), daemon=True)
        err_thread = threading.Thread(target=drain_stderr, daemon=True)
        out_thread.start()
        err_thread.start()

        timed_out = False
        try:
            proc.wait(timeout=deadline_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(proc)

        # Bounded join: readers exit once the pipes close after process death.
        out_thread.join(timeout=_GRACE_PERIOD_S)
        err_thread.join(timeout=_GRACE_PERIOD_S)

    return _ProcessOutcome(
        records=records,
        malformed_lines=malformed,
        stderr="".join(stderr_chunks),
        returncode=proc.returncode,
        timed_out=timed_out,
    )


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole group, then SIGKILL. Child tools (pytest, node) must die too —
    a survivor would keep mutating the worktree while the patch is being exported."""
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, AttributeError):
        pgid = None

    def signal_group(sig: int) -> None:
        if pgid is not None and hasattr(os, "killpg"):
            try:
                os.killpg(pgid, sig)
                return
            except OSError:
                pass
        try:
            proc.send_signal(sig)
        except OSError:
            pass

    signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=_GRACE_PERIOD_S)
        return
    except subprocess.TimeoutExpired:
        pass
    signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=_GRACE_PERIOD_S)
    except subprocess.TimeoutExpired:
        pass


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class ClaudeCodeAdapter:
    name = "claude_code"

    def __init__(self, config: ClaudeCodeConfig | None = None) -> None:
        self.config = config or ClaudeCodeConfig()
        self.adapter_version = "unknown"
        self._task: AgentTask | None = None
        self._budget: BudgetContract | None = None
        self._sandbox: WorktreeSandbox | None = None
        self._workdir: Path | None = None
        self._config_dir: Path | None = None
        self._session_id: str | None = None
        self._session_result: AgentRunResult | None = None
        self._session_native_log: Path | None = None
        self._probe_cache: ProbeResult | None = None

    # -- capability contract ------------------------------------------------ #
    def probe(self) -> ProbeResult:
        if self._probe_cache is not None:
            return self._probe_cache
        resolved = shutil.which(self.config.cli_path)
        if resolved is None:
            result = ProbeResult(
                adapter=self.name,
                available=False,
                version="unknown",
                detail=(
                    f"claude CLI not found on PATH as {self.config.cli_path!r}; "
                    "install Claude Code or set ClaudeCodeConfig.cli_path"
                ),
            )
            self._probe_cache = result
            return result
        try:
            proc = subprocess.run(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=self.config.probe_timeout_s,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            result = ProbeResult(
                adapter=self.name, available=False, version="unknown", detail=f"probe failed: {exc}"
            )
            self._probe_cache = result
            return result
        if proc.returncode != 0:
            result = ProbeResult(
                adapter=self.name,
                available=False,
                version="unknown",
                detail=f"`claude --version` exited {proc.returncode}: {proc.stderr.strip()[:200]}",
            )
            self._probe_cache = result
            return result

        version = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else "unknown"
        self.adapter_version = version
        result = ProbeResult(adapter=self.name, available=True, version=version)
        self._probe_cache = result
        return result

    def capabilities(self) -> set[Capability]:
        caps = {
            Capability.PLANNING,
            Capability.MEMORY,
            Capability.COMPACTION,
            Capability.MULTI_TURN,
            Capability.SUBAGENT,
        }
        if self._native_cost_trusted():
            caps.add(Capability.NATIVE_COST)
        return caps

    # -- lifecycle ---------------------------------------------------------- #
    def prepare(
        self,
        workdir: Path,
        task: AgentTask,
        budget: BudgetContract,
        *,
        runtime: object | None = None,
    ) -> None:
        if not isinstance(runtime, WorktreeSandbox):
            raise TypeError("ClaudeCodeAdapter requires a WorktreeSandbox runtime")
        if workdir.resolve() != runtime.root.resolve():
            raise ValueError("workdir and sandbox root must identify the same workspace")
        if budget.max_cost_usd is not None:
            raise UnsupportedCapability(
                "claude CLI exposes no hard cost ceiling; cost is observed, not enforced"
            )
        if budget.max_tokens is not None:
            raise UnsupportedCapability("claude CLI exposes no aggregate token ceiling")

        self._task = task
        self._budget = budget
        self._sandbox = runtime
        self._workdir = workdir.resolve()
        self._session_id = None
        self._session_result = None
        self._session_native_log = None
        if self.config.isolate_config:
            self._config_dir = Path(tempfile.mkdtemp(prefix="cae-claude-cfg-"))

    def run(self, instruction: str) -> AgentRunResult:
        return self._invoke(instruction, resume=False)

    def continue_(self, feedback: str) -> AgentRunResult:
        if self._session_id is None:
            raise UnsupportedCapability(
                "no Claude Code session to continue; run() must succeed with a session_id first"
            )
        exhausted = self._session_budget_exhausted()
        if exhausted is not None:
            return exhausted
        return self._invoke(feedback, resume=True)

    def cleanup(self) -> None:
        if self._config_dir is not None:
            shutil.rmtree(self._config_dir, ignore_errors=True)
        self._task = None
        self._budget = None
        self._sandbox = None
        self._workdir = None
        self._config_dir = None
        self._session_id = None
        self._session_result = None
        self._session_native_log = None

    # -- execution ---------------------------------------------------------- #
    def _invoke(self, prompt: str, *, resume: bool) -> AgentRunResult:
        if self._task is None or self._budget is None or self._sandbox is None or self._workdir is None:
            raise RuntimeError("adapter must be prepared before run")
        probe = self.probe()
        if not probe.available:
            raise UnsupportedCapability(probe.detail or "claude CLI unavailable")

        budget = self._budget
        raw_log = self._native_log_path()
        started_at = utc_now_iso()
        started = time.monotonic()

        remaining_wall_clock = self._remaining_wall_clock_s()
        outcome = _stream_process(
            self._build_argv(prompt, resume=resume),
            cwd=self._workdir,
            env=self._child_env(),
            deadline_s=remaining_wall_clock,
            raw_log=raw_log,
            append=resume,
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        if outcome.launch_error is not None:
            raise UnsupportedCapability(f"failed to launch claude CLI: {outcome.launch_error}")

        parsed = parse_stream_json(outcome.records, malformed_lines=outcome.malformed_lines)
        self._session_id = parsed.session_id or self._session_id
        if outcome.stderr.strip():
            raw_log.with_suffix(".stderr.log").write_text(outcome.stderr, encoding="utf-8")

        removed_artifacts = self._strip_harness_artifacts()
        patch = self._sandbox.export_patch()
        changed_files = self._sandbox.changed_files()

        stop_reason = self._stop_reason(parsed, outcome)
        cost_trusted = self._native_cost_trusted() and parsed.total_cost_usd is not None
        segment = AgentRunResult(
            adapter=self.name,
            adapter_version=probe.version,
            patch=patch,
            changed_files=changed_files,
            events=parsed.events,
            native_trajectory_path=str(raw_log),
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            cached_tokens=parsed.cached_tokens,
            cost_usd=parsed.total_cost_usd if cost_trusted else None,
            cost_source="native" if cost_trusted else "unavailable",
            stop_reason=stop_reason,
            native_stop_reason=self._native_stop_reason(parsed, outcome),
            duration_ms=duration_ms,
            budget=budget,
            env_manifest=self._env_manifest(parsed, outcome, removed_artifacts),
            steps=parsed.model_turns,
            tool_call_count=parsed.tool_calls,
            plan=_plan_from_events(parsed),
            final_message=parsed.final_message,
            completion_checks={
                "has_changes": bool(changed_files),
                "ran_tests": parsed.ran_tests,
                "last_test_passed": parsed.last_test_ok is True,
                "uncommitted_diff": bool(patch.strip()),
                "over_steps": stop_reason == "budget_steps",
                "over_timeout": stop_reason == "budget_time",
                "triggered_forbidden": False,
                "blocked_commands": 0,
                "provider_error": stop_reason == "error",
                # Claude Code runs its own tools, so the MiniAgent's CommandPolicy never
                # applies. Surfaced per trial because it is a comparability caveat, not a bug.
                "command_policy_enforced": False,
            },
            started_at=started_at,
            finished_at=utc_now_iso(),
        )
        result = self._merge_session_result(segment) if resume else segment
        self._session_result = result
        return result

    def _build_argv(self, prompt: str, *, resume: bool) -> list[str]:
        argv = [self.config.cli_path, "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if resume and self._session_id:
            argv += ["--resume", self._session_id]
        if self._budget and self._budget.max_steps is not None:
            used = self._session_result.steps if self._session_result else 0
            argv += ["--max-turns", str(max(1, self._budget.max_steps - used))]
        if self.config.model:
            argv += ["--model", self.config.model]
        if self.config.permission_mode:
            argv += ["--permission-mode", self.config.permission_mode]
        argv += list(self.config.extra_args)
        return argv

    def _remaining_wall_clock_s(self) -> float:
        assert self._budget is not None
        used = (self._session_result.duration_ms / 1000) if self._session_result else 0.0
        return max(0.001, self._budget.max_wall_clock_s - used)

    def _session_budget_exhausted(self) -> AgentRunResult | None:
        if self._session_result is None or self._budget is None:
            return None
        reason = None
        if self._session_result.duration_ms >= self._budget.max_wall_clock_s * 1000:
            reason = "budget_time"
        elif (
            self._budget.max_steps is not None
            and self._session_result.steps >= self._budget.max_steps
        ):
            reason = "budget_steps"
        if reason is None:
            return None
        checks = {
            **self._session_result.completion_checks,
            "over_timeout": reason == "budget_time",
            "over_steps": reason == "budget_steps",
        }
        exhausted = self._session_result.model_copy(
            update={"stop_reason": reason, "final_message": None, "completion_checks": checks}
        )
        self._session_result = exhausted
        return exhausted

    def _merge_session_result(self, segment: AgentRunResult) -> AgentRunResult:
        """Return one cumulative result for the whole resumed CLI session."""
        previous = self._session_result
        if previous is None:
            return segment
        checks = {
            **segment.completion_checks,
            "has_changes": bool(segment.changed_files),
            "ran_tests": bool(
                previous.completion_checks.get("ran_tests")
                or segment.completion_checks.get("ran_tests")
            ),
            "provider_error": bool(
                previous.completion_checks.get("provider_error")
                or segment.completion_checks.get("provider_error")
            ),
            "session_invocations": int(
                previous.completion_checks.get("session_invocations", 1)
            ) + 1,
            # Claude's resume result does not document whether total_cost_usd is incremental
            # or cumulative. Summing it may double-count; taking the last value may omit the
            # first turn. Until that contract is verified, multi-turn native cost is unknown.
            "multi_turn_cost_reason": "resume cost accumulation semantics are unverified",
        }
        shifted_events = [
            event.model_copy(update={"step": event.step + previous.steps})
            for event in segment.events
        ]
        return segment.model_copy(update={
            "events": [*previous.events, *shifted_events],
            "prompt_tokens": previous.prompt_tokens + segment.prompt_tokens,
            "completion_tokens": previous.completion_tokens + segment.completion_tokens,
            "cached_tokens": previous.cached_tokens + segment.cached_tokens,
            "cost_usd": None,
            "cost_source": "unavailable",
            "duration_ms": previous.duration_ms + segment.duration_ms,
            "steps": previous.steps + segment.steps,
            "tool_call_count": previous.tool_call_count + segment.tool_call_count,
            "llm_calls": [*previous.llm_calls, *segment.llm_calls],
            "completion_checks": checks,
            "started_at": previous.started_at,
        })

    def _child_env(self) -> dict[str, str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if k in self.config.env_allowlist or k.startswith(self.config.env_prefixes)
        }
        if self._config_dir is not None:
            env["CLAUDE_CONFIG_DIR"] = str(self._config_dir)
        # Deterministic, non-interactive output regardless of the operator's shell.
        # PYTHONDONTWRITEBYTECODE matches the MiniAgent sandbox: bytecode written by a test
        # run is build residue, not the agent's change, and letting one adapter emit it and
        # not the other would make changed-file counts incomparable.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CI"] = "1"
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"
        return env

    def _native_log_path(self) -> Path:
        if self._session_native_log is not None:
            return self._session_native_log
        case = (self._task.case_id if self._task else None) or "trial"
        safe_case = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in case)
        # Absolute: the recorded path is provenance, and a relative one silently changes
        # meaning when an artifact is read from a different working directory.
        self._session_native_log = (
            self.config.native_log_dir.resolve() / f"{self.name}-{safe_case}-{uuid4().hex[:8]}.jsonl"
        )
        return self._session_native_log

    def _strip_harness_artifacts(self) -> list[str]:
        """Remove CLI-authored scaffolding that was not present at the base commit."""
        if self._sandbox is None or self._workdir is None:
            return []
        removed: list[str] = []
        for rel in self.config.harness_artifacts:
            target = self._workdir / rel
            if not target.exists() or self._tracked_at_base(rel):
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            removed.append(rel)
        return removed

    def _tracked_at_base(self, rel: str) -> bool:
        assert self._workdir is not None
        proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", rel],
            cwd=str(self._workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(proc.stdout.strip())

    # -- interpretation ----------------------------------------------------- #
    def _stop_reason(self, parsed: ParsedStream, outcome: _ProcessOutcome) -> CanonicalStopReason:
        if outcome.timed_out:
            return "budget_time"
        if parsed.saw_result:
            mapped = _RESULT_SUBTYPE_STOP.get(str(parsed.result_subtype), "error")
            return "error" if parsed.is_error and mapped == "final" else mapped
        return "error"

    def _native_stop_reason(self, parsed: ParsedStream, outcome: _ProcessOutcome) -> str:
        if outcome.timed_out:
            return "wall_clock_timeout"
        if parsed.saw_result:
            return str(parsed.result_subtype or "result_without_subtype")
        return f"no_result_record(exit={outcome.returncode})"

    def _native_cost_trusted(self) -> bool:
        if self.config.trust_native_cost is not None:
            return self.config.trust_native_cost
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
        if not base_url:
            return True
        return base_url.startswith(TRUSTED_COST_ENDPOINT_PREFIXES)

    def _env_manifest(
        self, parsed: ParsedStream, outcome: _ProcessOutcome, removed_artifacts: list[str]
    ) -> dict[str, Any]:
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cli_path": shutil.which(self.config.cli_path),
            "cli_version": self.adapter_version,
            "model_requested": self.config.model,
            "model_reported": parsed.model,
            "permission_mode": self.config.permission_mode,
            "extra_args": list(self.config.extra_args),
            "session_id": parsed.session_id,
            "tools_offered": parsed.tools_offered,
            "anthropic_base_url": base_url or None,
            "native_cost_trusted": self._native_cost_trusted(),
            "usage_source": parsed.usage_source,
            "config_isolated": self.config.isolate_config,
            # A non-isolated run reads the operator's personal settings/hooks/MCP servers and
            # is therefore not reproducible on another machine. Recorded so reports can say so.
            "reproducible_config": self.config.isolate_config,
            "command_policy_enforced": False,
            "removed_harness_artifacts": removed_artifacts,
            "malformed_stream_lines": parsed.malformed_lines,
            "unknown_record_types": parsed.unknown_record_types,
            "process_exit_code": outcome.returncode,
            "stderr_bytes": len(outcome.stderr.encode("utf-8")),
            "repo_commit": _git_head(self._workdir) if self._workdir else None,
        }


def _plan_from_events(parsed: ParsedStream) -> dict[str, Any]:
    """Claude Code's last TodoWrite, in the same shape the MiniAgent planner reports.

    Only the plan itself is recovered. Adherence is intentionally not computed here: the
    MiniAgent's figure is derived from a tracker that watched every repo action as it
    happened, and reconstructing an equivalent from a normalized trace would produce a
    number that looks comparable without being so.
    """
    updates = [e for e in parsed.events if e.type is TraceEventType.PLAN_UPDATE]
    if not updates:
        return {}
    latest = updates[-1].payload.get("plan")
    return {
        "items": latest if isinstance(latest, list) else [],
        "stats": {
            "plan_declared": True,
            "plan_revisions": len(updates),
            "plan_adherence": None,
            "plan_adherence_unavailable_reason": "native plan; adherence is not reconstructed",
        },
    }


def _git_head(workdir: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


__all__ = [
    "ClaudeCodeAdapter",
    "ClaudeCodeConfig",
    "ParsedStream",
    "is_test_command",
    "parse_stream_json",
]
