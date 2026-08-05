"""Adapter for the Cline CLI (https://cline.bot), driven headless.

Cline is the second external framework behind this project's ``AgentAdapter`` protocol, and
adding it is what turns that protocol from an assertion into a measured claim. Everything the
Claude Code adapter established still applies — isolated config, honest cost provenance,
raw trajectory retained on disk — plus one thing specific to Cline.

**Tool detail comes from the session store, not the stream.** ``cline --json`` emits
``hook_event`` lines for every tool call, but they carry only a timestamp and an agent id: no
tool name, no path, no command. Counting is possible; attribution is not. The canary detector
needs the path of every write and the failure taxonomy needs the text of every command, so
both would silently degrade — the canary would observe zero edits and report perfect
adherence. Cline does persist the full conversation, tool inputs included, under its
``--data-dir``, so the trajectory is reconstructed from there after the run. Reading state the
CLI already writes leaves the run itself untouched, which injecting a hook would not.

The stream is still consumed and still streamed to disk: it is what makes a budget-killed
trial diagnosable, and it carries the usage and finish-reason records the session file does
not summarize.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeagent_eval.adapters.base import (
    AgentRunResult,
    BudgetContract,
    CanonicalStopReason,
    Capability,
    ProbeResult,
    UnsupportedCapability,
)
from codeagent_eval.adapters.normalize import ToolSemantics, is_test_command
from codeagent_eval.adapters.process import ProcessOutcome, stream_process
from codeagent_eval.models import AgentTask, TraceEvent, TraceEventType, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

#: Cline's tool vocabulary. ``editor`` covers create/replace/delete through one entry point,
#: and ``run_commands`` takes a list, so one call can be several commands.
CLINE_SEMANTICS = ToolSemantics(
    read=frozenset({"read_files", "list_files", "search_files", "grep_files"}),
    write=frozenset({"editor", "write_to_file", "replace_in_file", "new_rule"}),
    command=frozenset({"run_commands", "execute_command"}),
    plan=frozenset({"plan_mode_respond", "todo_write", "update_todo_list"}),
)

#: Files Cline may leave in the workspace that are its own bookkeeping rather than the
#: agent's work. Counting them as changed files would fail the engineering constraints.
DEFAULT_HARNESS_ARTIFACTS = (".clinerules", ".clineignore", ".cline")

#: Environment passed to the child. Deliberately small: an agent inheriting the operator's
#: whole environment can reach credentials the experiment never declared.
DEFAULT_ENV_ALLOWLIST = frozenset({"HOME", "PATH", "SHELL", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR"})

#: Cline reports ``totalCost`` from its own price table, which is right only when the model is
#: being served by the provider that table describes. Pointed at a third-party
#: OpenAI-compatible endpoint — which is exactly how this project controls for the model —
#: the number is computed from the wrong prices, so it is recorded as unavailable rather than
#: reported as a cost. There is no endpoint at which it is currently trusted; the constant
#: exists so that becomes a one-line change with a visible rationale rather than a rewrite.
TRUSTED_COST_ENDPOINTS: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClineConfig:
    cli_path: str = "cline"
    #: Provider id understood by ``cline auth``. ``openai`` selects its OpenAI-compatible
    #: client, which is what a Zhipu/DeepSeek-style endpoint needs.
    provider: str = "openai"
    model: str | None = None
    api_key_env: str = "ZHIPU_API_KEY"
    base_url_env: str = "ZHIPU_BASE_URL"
    #: Explicit values win over the environment variables above when set.
    api_key: str | None = None
    base_url: str | None = None
    compaction: str = "agentic"
    extra_args: tuple[str, ...] = ()
    isolate_config: bool = True
    native_log_dir: Path = Path("artifacts/native_trajectories")
    harness_artifacts: tuple[str, ...] = DEFAULT_HARNESS_ARTIFACTS
    env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST
    probe_timeout_s: int = 30


@dataclass
class ParsedSession:
    """What one Cline run yields once its stream and session store are read together."""

    events: list[TraceEvent] = field(default_factory=list)
    model_turns: int = 0
    tool_calls: int = 0
    final_message: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    native_cost_usd: float | None = None
    duration_ms: int = 0
    session_id: str | None = None
    served_model: str | None = None
    #: Session files that could not be read. Non-zero means the trajectory is incomplete and
    #: the detectors are seeing less than happened, so it is surfaced rather than swallowed.
    unreadable_sessions: int = 0


# --------------------------------------------------------------------------- #
# Reading what Cline recorded
# --------------------------------------------------------------------------- #
def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def parse_stream(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull the run-level facts out of ``--json`` output.

    Only ``run_result`` and ``usage`` are taken from here. Tool detail deliberately is not:
    the stream's hook events cannot supply it, and half-reading it from two sources would
    produce a trajectory whose gaps are invisible.
    """
    summary: dict[str, Any] = {
        "finish_reason": None, "iterations": 0, "duration_ms": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
        "native_cost_usd": None, "session_id": None, "tool_calls": 0,
    }
    for record in records:
        kind = record.get("type")
        if kind == "hook_event":
            if record.get("hookEventName") == "tool_call":
                summary["tool_calls"] += 1
            if not summary["session_id"]:
                summary["session_id"] = record.get("taskId") or None
        elif kind == "run_result":
            usage = record.get("aggregateUsage") or record.get("usage") or {}
            summary["finish_reason"] = record.get("finishReason")
            summary["iterations"] = _as_int(record.get("iterations"))
            summary["duration_ms"] = _as_int(record.get("durationMs"))
            summary["prompt_tokens"] = _as_int(usage.get("inputTokens"))
            summary["completion_tokens"] = _as_int(usage.get("outputTokens"))
            summary["cached_tokens"] = _as_int(usage.get("cacheReadTokens"))
            cost = usage.get("totalCost")
            summary["native_cost_usd"] = float(cost) if isinstance(cost, int | float) else None
    return summary


def _write_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    """Every path a call touches, however that framework spells it.

    The canary checker matches on ``payload["path"]``, so a write whose path is not surfaced
    here is a write the detector cannot see — and an unseen violation reads as compliance.
    """
    paths: list[str] = []
    for key in ("path", "file_path", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for key in ("files", "paths"):
        for item in tool_input.get(key) or ():
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                inner = item.get("path") or item.get("file_path")
                if isinstance(inner, str):
                    paths.append(inner)
    return paths


def _commands(tool_input: dict[str, Any]) -> list[str]:
    single = tool_input.get("command")
    if isinstance(single, str) and single:
        return [single]
    return [c for c in (tool_input.get("commands") or ()) if isinstance(c, str) and c]


def parse_session_file(path: Path, parsed: ParsedSession, *, start_step: int = 0) -> int:
    """Turn one persisted Cline conversation into normalized trace events.

    Returns the last step number used, so several session files (a resumed multi-turn run
    writes more than one) stay on a single monotonic step axis.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    messages = document.get("messages")
    if not isinstance(messages, list):
        return start_step

    step = start_step
    parsed.session_id = document.get("sessionId") or parsed.session_id
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            step += 1
            parsed.model_turns += 1
            model_info = message.get("modelInfo") or {}
            served = model_info.get("id")
            if isinstance(served, str) and served:
                # The model that actually answered, not the one requested. An experiment
                # whose artifacts name a model that never ran is worse than one that fails.
                parsed.served_model = served
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or "unknown"
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            parsed.tool_calls += 1
            commands = _commands(tool_input)
            paths = _write_paths(name, tool_input)
            event_type = CLINE_SEMANTICS.classify(
                name, command=" ".join(commands) if commands else None
            )
            payload: dict[str, Any] = {
                "tool": name,
                "arguments": tool_input,
                "native_tool": name,
                "known_tool": CLINE_SEMANTICS.knows(name),
            }
            if paths:
                payload["path"] = paths[0]
                payload["paths"] = paths
            if commands:
                payload["command"] = commands[0]
                payload["commands"] = commands
                payload["is_test_command"] = any(is_test_command(c) for c in commands)
            parsed.events.append(
                TraceEvent(step=step, type=TraceEventType.TOOL_CALL, name=name, payload=payload)
            )
            parsed.events.append(TraceEvent(step=step, type=event_type, name=name, payload=payload))
    return step


def collect_session_events(data_dir: Path, parsed: ParsedSession) -> None:
    """Read every conversation Cline persisted for this run, oldest first."""
    sessions_root = data_dir / "sessions"
    if not sessions_root.is_dir():
        return
    files = sorted(sessions_root.glob("*/*.messages.json"), key=lambda p: p.stat().st_mtime)
    step = 0
    for file in files:
        try:
            step = parse_session_file(file, parsed, start_step=step)
        except (OSError, json.JSONDecodeError):
            parsed.unreadable_sessions += 1


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class ClineAdapter:
    """Drives the Cline CLI over one prepared worktree."""

    name = "cline"

    def __init__(self, config: ClineConfig | None = None) -> None:
        self.config = config or ClineConfig()
        self._task: AgentTask | None = None
        self._budget: BudgetContract | None = None
        self._sandbox: WorktreeSandbox | None = None
        self._workdir: Path | None = None
        self._data_dir: Path | None = None
        self._owns_data_dir = False
        self._session_result: AgentRunResult | None = None
        self._adapter_version: str | None = None

    # -- lifecycle ---------------------------------------------------------- #
    def probe(self) -> ProbeResult:
        executable = shutil.which(self.config.cli_path)
        if executable is None:
            return ProbeResult(
                adapter=self.name, available=False, version="unknown",
                detail=f"{self.config.cli_path!r} not found on PATH",
            )
        try:
            done = subprocess.run(
                [executable, "--version"], capture_output=True, text=True,
                timeout=self.config.probe_timeout_s, check=False,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return ProbeResult(adapter=self.name, available=False, version="unknown", detail=str(exc))
        version = (done.stdout or done.stderr).strip().splitlines()[:1]
        version_str = version[0] if version else "unknown"
        if done.returncode != 0:
            return ProbeResult(
                adapter=self.name, available=False, version=version_str,
                detail=f"`{self.config.cli_path} --version` exited {done.returncode}",
            )
        self._adapter_version = version_str
        return ProbeResult(adapter=self.name, available=True, version=version_str)

    @property
    def adapter_version(self) -> str:
        return self._adapter_version or "unknown"

    def capabilities(self) -> set[Capability]:
        # No NATIVE_COST: see TRUSTED_COST_ENDPOINTS. No MEMORY: .clinerules persistence is a
        # cross-run capability this harness deliberately does not enable, since it would
        # carry state between trials that are supposed to be independent.
        return {Capability.COMPACTION, Capability.MULTI_TURN, Capability.PLANNING}

    def prepare(
        self, workspace: Path, task: AgentTask, budget: BudgetContract, *, runtime=None
    ) -> None:
        if budget.max_tokens is not None:
            raise UnsupportedCapability(
                "cline does not accept an external context ceiling; it manages its own window"
            )
        self._task = task
        self._budget = budget
        self._sandbox = runtime
        self._workdir = Path(workspace)
        self._session_result = None

        if self.config.isolate_config:
            self._data_dir = Path(tempfile.mkdtemp(prefix="algora-cline-"))
            self._owns_data_dir = True
        else:
            self._data_dir = Path.home() / ".cline"
            self._owns_data_dir = False
        self._authenticate()

    def run(self, instruction: str) -> AgentRunResult:
        return self._invoke(instruction, resume=False)

    def continue_(self, feedback: str) -> AgentRunResult:
        if self._session_result is None:
            raise UnsupportedCapability("run() must start a Cline session before continue_()")
        exhausted = self._session_budget_exhausted()
        if exhausted is not None:
            return exhausted
        return self._invoke(feedback, resume=True)

    def cleanup(self) -> None:
        if self._owns_data_dir and self._data_dir is not None:
            shutil.rmtree(self._data_dir, ignore_errors=True)
        self._task = None
        self._budget = None
        self._sandbox = None
        self._workdir = None
        self._data_dir = None
        self._owns_data_dir = False
        self._session_result = None

    # -- execution ---------------------------------------------------------- #
    def _authenticate(self) -> None:
        """Write provider credentials into the isolated data dir before the first run."""
        key = self.config.api_key or os.environ.get(self.config.api_key_env)
        if not key:
            raise UnsupportedCapability(
                f"no API key: set {self.config.api_key_env} or ClineConfig.api_key"
            )
        argv = [
            self.config.cli_path, "auth",
            "--provider", self.config.provider,
            "--apikey", key,
            "--data-dir", str(self._data_dir),
            "--cwd", str(self._workdir),
        ]
        if self.config.model:
            argv += ["--modelid", self.config.model]
        base_url = self.config.base_url or os.environ.get(self.config.base_url_env)
        if base_url:
            argv += ["--baseurl", base_url.rstrip("/")]
        done = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=self.config.probe_timeout_s, check=False, env=self._child_env(),
        )
        if done.returncode != 0:
            raise UnsupportedCapability(
                f"cline auth failed ({done.returncode}): {(done.stderr or done.stdout).strip()[:300]}"
            )

    def _invoke(self, prompt: str, *, resume: bool) -> AgentRunResult:
        if self._task is None or self._budget is None or self._workdir is None:
            raise RuntimeError("adapter must be prepared before run")
        probe = self.probe()
        if not probe.available:
            raise UnsupportedCapability(probe.detail or "cline CLI unavailable")

        raw_log = self._native_log_path()
        started_at = utc_now_iso()
        started = time.monotonic()
        remaining = self._remaining_wall_clock_s()

        outcome = stream_process(
            self._build_argv(prompt, resume=resume),
            cwd=self._workdir,
            env=self._child_env(),
            deadline_s=remaining,
            raw_log=raw_log,
            append=resume,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if outcome.launch_error is not None:
            raise UnsupportedCapability(f"failed to launch cline CLI: {outcome.launch_error}")
        if outcome.stderr.strip():
            raw_log.with_suffix(".stderr.log").write_text(outcome.stderr, encoding="utf-8")

        summary = parse_stream(outcome.records)
        parsed = ParsedSession(
            finish_reason=summary["finish_reason"],
            prompt_tokens=summary["prompt_tokens"],
            completion_tokens=summary["completion_tokens"],
            cached_tokens=summary["cached_tokens"],
            native_cost_usd=summary["native_cost_usd"],
            duration_ms=summary["duration_ms"] or duration_ms,
            session_id=summary["session_id"],
        )
        collect_session_events(self._data_dir, parsed)
        if parsed.tool_calls == 0 and summary["tool_calls"] > 0:
            # The stream saw tool calls the session store did not yield. Rather than report a
            # trajectory the detectors would read as "made no edits", say so out loud.
            parsed.unreadable_sessions += 1

        removed = self._strip_harness_artifacts()
        patch = self._sandbox.export_patch() if self._sandbox is not None else ""
        changed = self._sandbox.changed_files() if self._sandbox is not None else []
        segment = AgentRunResult(
            adapter=self.name,
            adapter_version=self.adapter_version,
            patch=patch,
            changed_files=list(changed),
            events=parsed.events,
            native_trajectory_path=str(raw_log),
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            cached_tokens=parsed.cached_tokens,
            cost_usd=None,
            cost_source="unavailable",
            stop_reason=self._stop_reason(parsed, outcome),
            native_stop_reason=self._native_stop_reason(parsed, outcome),
            duration_ms=duration_ms,
            budget=self._budget,
            env_manifest=self._env_manifest(parsed, outcome, removed),
            steps=parsed.model_turns,
            tool_call_count=parsed.tool_calls,
            final_message=parsed.final_message,
            completion_checks=self._completion_checks(parsed, changed),
            started_at=started_at,
            finished_at=utc_now_iso(),
        )
        result = self._merge_session_result(segment) if resume else segment
        self._session_result = result
        return result

    def _build_argv(self, prompt: str, *, resume: bool) -> list[str]:
        argv = [
            self.config.cli_path, "--json",
            "--auto-approve", "true",
            "--cwd", str(self._workdir),
            "--data-dir", str(self._data_dir),
            "--compaction", self.config.compaction,
        ]
        if self.config.model:
            argv += ["--model", self.config.model]
        if resume and self._session_result is not None:
            session_id = (self._session_result.env_manifest or {}).get("cline_session_id")
            if session_id:
                argv += ["--id", str(session_id)]
        argv += list(self.config.extra_args)
        argv.append(prompt)
        return argv

    def _child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in self.config.env_allowlist}
        # Parity with every other arm: stray .pyc files are not the agent's work, and counting
        # them as changed files has previously turned a compliant run into a violation.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CI"] = "1"
        return env

    def _native_log_path(self) -> Path:
        root = Path(self.config.native_log_dir)
        root.mkdir(parents=True, exist_ok=True)
        case_id = getattr(self._task, "case_id", None) or "trial"
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(case_id))
        return root / f"cline-{safe}-{int(time.time() * 1000)}.jsonl"

    def _strip_harness_artifacts(self) -> list[str]:
        """Delete Cline's own bookkeeping files, unless the repo already tracked them."""
        if self._workdir is None:
            return []
        removed: list[str] = []
        for name in self.config.harness_artifacts:
            target = self._workdir / name
            if not target.exists() or self._tracked_at_base(name):
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            removed.append(name)
        return removed

    def _tracked_at_base(self, rel: str) -> bool:
        if self._workdir is None:
            return False
        done = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=str(self._workdir), capture_output=True, text=True, check=False,
        )
        return done.returncode == 0

    # -- budget and interpretation ------------------------------------------ #
    def _remaining_wall_clock_s(self) -> float:
        assert self._budget is not None
        used = (self._session_result.duration_ms / 1000) if self._session_result else 0.0
        return max(0.001, self._budget.max_wall_clock_s - used)

    def _session_budget_exhausted(self) -> AgentRunResult | None:
        if self._session_result is None or self._budget is None:
            return None
        reason: CanonicalStopReason | None = None
        if self._session_result.duration_ms >= self._budget.max_wall_clock_s * 1000:
            reason = "budget_time"
        elif (
            self._budget.max_steps is not None
            and self._session_result.steps >= self._budget.max_steps
        ):
            reason = "budget_steps"
        if reason is None:
            return None
        exhausted = self._session_result.model_copy(update={
            "stop_reason": reason,
            "native_stop_reason": "budget_exhausted_before_followup",
            "completion_checks": {
                **self._session_result.completion_checks,
                "budget_exhausted_before_followup": True,
            },
        })
        self._session_result = exhausted
        return exhausted

    def _stop_reason(self, parsed: ParsedSession, outcome: ProcessOutcome) -> CanonicalStopReason:
        if outcome.timed_out:
            return "budget_time"
        if parsed.finish_reason in ("completed", "stop", "end_turn"):
            return "final"
        if parsed.finish_reason in ("max_iterations", "max_retries", "max_consecutive_mistakes"):
            return "budget_steps"
        if parsed.finish_reason == "timeout":
            return "budget_time"
        if parsed.finish_reason is None and outcome.returncode not in (0, None):
            return "error"
        return "final" if parsed.finish_reason is None else "error"

    def _native_stop_reason(self, parsed: ParsedSession, outcome: ProcessOutcome) -> str:
        if outcome.timed_out:
            return "harness_wall_clock_kill"
        return parsed.finish_reason or f"exit_{outcome.returncode}"

    def _completion_checks(self, parsed: ParsedSession, changed: list[str]) -> dict[str, Any]:
        ran_tests = any(
            event.payload.get("is_test_command")
            for event in parsed.events
            if event.type is TraceEventType.TOOL_CALL
        )
        checks: dict[str, Any] = {
            "has_changes": bool(changed),
            "ran_tests": bool(ran_tests),
            "provider_error": parsed.finish_reason in ("error", "api_error"),
        }
        if parsed.unreadable_sessions:
            # Loud, because a short trajectory and an unread trajectory look identical to
            # every detector downstream.
            checks["trajectory_incomplete"] = True
            checks["unreadable_sessions"] = parsed.unreadable_sessions
        return checks

    def _env_manifest(
        self, parsed: ParsedSession, outcome: ProcessOutcome, removed: list[str]
    ) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "adapter_version": self.adapter_version,
            "cli_path": shutil.which(self.config.cli_path),
            "provider": self.config.provider,
            "requested_model": self.config.model,
            "served_model": parsed.served_model,
            "base_url": self.config.base_url or os.environ.get(self.config.base_url_env),
            "compaction": self.config.compaction,
            "isolated_config": self.config.isolate_config,
            "cline_session_id": parsed.session_id,
            "native_cost_usd_untrusted": parsed.native_cost_usd,
            "cost_provenance": "cline price table does not describe this endpoint",
            "malformed_stream_lines": outcome.malformed_lines,
            "unreadable_sessions": parsed.unreadable_sessions,
            "removed_harness_artifacts": removed,
            "platform": platform.platform(),
            "python": platform.python_version(),
        }

    def _merge_session_result(self, segment: AgentRunResult) -> AgentRunResult:
        """One cumulative result for a resumed session, so budgets stay comparable."""
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
        }
        # Session events are re-read in full from the store each turn, so the later parse
        # already contains the earlier turns; concatenating would double the trajectory.
        return segment.model_copy(update={
            "prompt_tokens": previous.prompt_tokens + segment.prompt_tokens,
            "completion_tokens": previous.completion_tokens + segment.completion_tokens,
            "cached_tokens": previous.cached_tokens + segment.cached_tokens,
            "cost_usd": None,
            "cost_source": "unavailable",
            "duration_ms": previous.duration_ms + segment.duration_ms,
            "completion_checks": checks,
        })
