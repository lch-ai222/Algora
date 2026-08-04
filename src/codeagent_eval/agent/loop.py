"""MiniAgent: the tool-using loop that turns an AgentTask into a repository change.

One trial = build the initial message → repeatedly ask the model for a tool turn → execute
tool calls in the sandbox → feed results back → stop on a final answer, step budget, wall-clock
timeout, provider failure, or (V2) a detected action loop. Everything is recorded as TraceEvents
plus the reused LlmCallRecords, so a trial is fully replayable and gradeable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from codeagent_eval.agent.planner import PlanTracker, parse_plan_items
from codeagent_eval.agent.prompts import build_system_prompt
from codeagent_eval.llm import LlmCallRecord, LlmProvider, llm_trace_scope
from codeagent_eval.models import AgentTask, TraceEvent, TraceEventType, utc_now_iso
from codeagent_eval.sandbox.worktree import WorktreeSandbox
from codeagent_eval.tools import ToolContext, ToolRegistry, default_tools


@dataclass
class AgentConfig:
    """Harness knobs. V1 is the thin baseline; V2 flips the discipline flags (M4)."""

    version: str = "v1"
    complexity: str = "fast"
    temperature: float = 0.0
    max_tokens: int = 2048
    # V2-only guards (kept off in V1 so its failure modes are real):
    detect_repeated_actions: bool = False
    repeated_action_limit: int = 3
    # V3-only: offers update_plan and tracks adherence. Off elsewhere so V1/V2 keep exactly
    # the toolset their calibrated baselines were measured with.
    enable_planner: bool = False


class TrialResult(BaseModel):
    stop_reason: str  # final | max_steps | timeout | provider_error | repeated_action
    # Framework-independent stop semantics, set by adapters. The MiniAgent's own vocabulary
    # doubles as the taxonomy's, but an external agent's native reasons ("error_max_turns")
    # do not, so attribution reads this field instead of pattern-matching native strings.
    canonical_stop_reason: str | None = None
    steps: int = 0
    tool_call_count: int = 0
    final_message: str | None = None
    patch: str = ""
    changed_files: list[str] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    llm_calls: list[LlmCallRecord] = Field(default_factory=list)
    cached_tokens: int = 0
    cost_usd: float | None = None
    cost_source: str = "unavailable"
    completion_checks: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0


@dataclass
class _RunState:
    events: list[TraceEvent] = field(default_factory=list)
    step: int = 0
    tool_calls: int = 0
    ran_tests: bool = False
    last_test_exit: int | None = None
    forbidden_attempts: int = 0
    blocked_commands: int = 0
    premature_final_attempts: int = 0
    action_signatures: list[str] = field(default_factory=list)
    planner: PlanTracker = field(default_factory=PlanTracker)
    #: Repo-affecting actions (edits and test runs) seen so far. Plan adherence is judged
    #: against this rather than against the agent's own claim that an item is finished.
    repo_actions: int = 0

    def emit(self, type_: TraceEventType, name: str | None = None, **payload: Any) -> None:
        self.events.append(TraceEvent(step=self.step, type=type_, name=name, payload=payload))


class MiniAgent:
    def __init__(
        self,
        provider: LlmProvider,
        config: AgentConfig | None = None,
        registry: ToolRegistry | None = None,
    ):
        self.provider = provider
        self.config = config or AgentConfig()
        self.registry = registry or ToolRegistry(
            default_tools(planning=self.config.enable_planner)
        )

    def run(self, task: AgentTask, sandbox: WorktreeSandbox, *, case_id: str | None = None) -> TrialResult:
        system_prompt = build_system_prompt(self.config.version, task.project_instructions)
        ctx = ToolContext(
            sandbox=sandbox,
            forbidden_paths=_forbidden_from_task(task),
            default_timeout=min(task.timeout_seconds, 120),
        )
        tools = self.registry.openai_tools()
        messages: list[dict[str, Any]] = [{"role": "user", "content": _initial_user_message(task, sandbox)}]

        state = _RunState()
        deadline = time.monotonic() + task.timeout_seconds
        started_at = utc_now_iso()
        started = time.monotonic()
        stop_reason = "max_steps"

        with llm_trace_scope(case_id=case_id, node_name=f"agent_{self.config.version}") as llm_records:
            for step in range(1, task.max_steps + 1):
                state.step = step
                if time.monotonic() > deadline:
                    stop_reason = "timeout"
                    break

                state.emit(TraceEventType.MODEL_REQUEST, name=f"step_{step}", message_count=len(messages))
                turn = self.provider.tool_completion(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    complexity=self.config.complexity,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    call_site=f"agent.{self.config.version}",
                    prompt_version=self.config.version,
                )
                if turn is None:
                    state.emit(TraceEventType.ERROR, name="provider_error", error=self.provider.last_error)
                    stop_reason = "provider_error"
                    break

                state.emit(
                    TraceEventType.MODEL_RESPONSE,
                    content=turn.content,
                    tool_calls=len(turn.tool_calls),
                    finish_reason=turn.finish_reason,
                )

                if not turn.tool_calls:
                    rejection_reasons = _completion_rejection_reasons(task, sandbox, state, turn)
                    if self.config.version == "v2" and rejection_reasons:
                        state.premature_final_attempts += 1
                        state.emit(
                            TraceEventType.ERROR,
                            name="premature_final",
                            reasons=rejection_reasons,
                            finish_reason=turn.finish_reason,
                        )
                        if turn.content:
                            messages.append({"role": "assistant", "content": turn.content})
                        messages.append(
                            {
                                "role": "user",
                                "content": _completion_feedback(rejection_reasons),
                            }
                        )
                        continue
                    state.emit(TraceEventType.FINAL_ANSWER, content=turn.content)
                    result_final = turn.content
                    stop_reason = "final"
                    return self._finalize(
                        task, sandbox, state, stop_reason, result_final, llm_records,
                        started_at, started,
                    )

                messages.append(_assistant_message(turn))
                looped = False
                for call in turn.tool_calls:
                    state.tool_calls += 1
                    signature = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
                    state.emit(TraceEventType.TOOL_CALL, name=call.name, arguments=call.arguments,
                               arguments_error=call.arguments_error)

                    if call.arguments_error:
                        tool_content = f"argument error: {call.arguments_error}"
                        state.emit(TraceEventType.TOOL_RESULT, name=call.name, ok=False, content=tool_content)
                        messages.append(_tool_message(call.call_id, tool_content))
                        continue

                    if self.config.detect_repeated_actions and _is_repeated(state, signature, self.config):
                        looped = True
                        break
                    state.action_signatures.append(signature)

                    result = self.registry.dispatch(ctx, call.name, call.arguments)
                    _record_side_events(state, call.name, call.arguments, result)
                    if call.name == "update_plan" and result.ok:
                        _record_plan(state, result)
                    messages.append(_tool_message(call.call_id, result.content))

                if looped:
                    state.emit(TraceEventType.ERROR, name="repeated_action", signature=state.action_signatures[-1])
                    stop_reason = "repeated_action"
                    break

        return self._finalize(task, sandbox, state, stop_reason, None, llm_records, started_at, started)

    def _finalize(
        self, task, sandbox, state, stop_reason, final_message, llm_records, started_at, started
    ) -> TrialResult:
        patch = sandbox.export_patch()
        changed = sandbox.changed_files()
        checks = {
            "has_changes": bool(changed),
            "ran_tests": state.ran_tests,
            "last_test_passed": state.last_test_exit == 0,
            "uncommitted_diff": bool(patch.strip()),  # trials never commit; diff is the deliverable
            "over_steps": stop_reason == "max_steps",
            "over_timeout": stop_reason == "timeout",
            "triggered_forbidden": state.forbidden_attempts > 0,
            "blocked_commands": state.blocked_commands,
            "provider_error": stop_reason == "provider_error",
            "premature_final_attempts": state.premature_final_attempts,
        }
        plan_stats = state.planner.stats() if self.config.enable_planner else {}
        return TrialResult(
            stop_reason=stop_reason,
            steps=state.step,
            tool_call_count=state.tool_calls,
            final_message=final_message,
            patch=patch,
            changed_files=changed,
            events=state.events,
            llm_calls=list(llm_records),
            completion_checks=checks,
            plan=(
                {"items": [i.model_dump(mode="json") for i in state.planner.current_items],
                 "stats": plan_stats}
                if self.config.enable_planner
                else {}
            ),
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_ms=int((time.monotonic() - started) * 1000),
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _forbidden_from_task(task: AgentTask) -> list[str]:
    # Task-level constraints will carry forbidden_paths in M2; default protects test files.
    return ["test_*.py", "*/test_*.py", "tests/*"]


def _initial_user_message(task: AgentTask, sandbox: WorktreeSandbox) -> str:
    top = "\n".join(sorted(p.name for p in sandbox.root.iterdir() if not p.name.startswith(".")))
    return (
        f"Task:\n{task.instruction}\n\n"
        f"You are in a git worktree at the repo root. Top-level entries:\n{top}\n\n"
        f"Budget: up to {task.max_steps} steps. Use the tools to inspect, edit, and verify."
    )


def _assistant_message(turn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content or "",
        "tool_calls": [
            {
                "id": c.call_id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in turn.tool_calls
        ],
    }


def _completion_rejection_reasons(
    task: AgentTask,
    sandbox: WorktreeSandbox,
    state: _RunState,
    turn,
) -> list[str]:
    """Return objective reasons why a V2 no-tool turn is not a valid completion."""
    reasons: list[str] = []
    if turn.finish_reason == "length":
        reasons.append("response was truncated by the per-call output-token limit")
    if not (turn.content or "").strip():
        reasons.append("final summary is empty")
    if task.require_tests_run_before_finish:
        if not sandbox.changed_files():
            reasons.append("no repository changes are present")
        if not state.ran_tests:
            reasons.append("required tests have not been run")
        elif state.last_test_exit != 0:
            reasons.append("the latest test run is failing")
    return reasons


def _completion_feedback(reasons: list[str]) -> str:
    joined = "; ".join(reasons)
    return (
        "You attempted to finish, but completion is not valid: "
        f"{joined}. Continue with the available tools. Keep reasoning concise, make the "
        "required code changes, rerun the relevant tests until they pass, inspect the diff, "
        "then provide a non-empty final summary."
    )


def _tool_message(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _is_repeated(state: _RunState, signature: str, config: AgentConfig) -> bool:
    recent = state.action_signatures[-(config.repeated_action_limit - 1):]
    return len(recent) == config.repeated_action_limit - 1 and all(s == signature for s in recent)


def _record_plan(state: _RunState, result) -> None:
    """Fold an accepted plan revision into the tracker, timestamped by repo actions so far."""
    items = parse_plan_items(result.data.get("plan"))
    revision = state.planner.record(state.step, items, state.repo_actions)
    state.emit(
        TraceEventType.PLAN_UPDATE,
        name=f"revision_{len(state.planner.revisions)}",
        items=[i.model_dump(mode="json") for i in revision.items],
        actions_at_revision=revision.actions_at_revision,
    )


def _record_side_events(state: _RunState, name: str, args: dict[str, Any], result) -> None:
    """Emit domain-specific trace events (richer than the generic TOOL_RESULT) so the trace
    viewer and graders can reason about tests/edits/commands directly."""
    if name == "run_command":
        exit_code = result.data.get("exit_code")
        command = str(args.get("command", ""))
        if command.strip().startswith("pytest") or "pytest" in command:
            state.ran_tests = True
            state.repo_actions += 1
            state.last_test_exit = exit_code
            state.emit(TraceEventType.TEST_RESULT, name=command, exit_code=exit_code, ok=result.ok)
        else:
            state.emit(TraceEventType.COMMAND_FINISH, name=command, exit_code=exit_code,
                       blocked=result.data.get("blocked", False))
        if result.data.get("blocked"):
            state.blocked_commands += 1
    elif name == "apply_patch":
        if result.ok:
            state.repo_actions += 1
        if result.data.get("forbidden"):
            state.forbidden_attempts += 1
        state.emit(TraceEventType.FILE_WRITE, name=str(args.get("path")), ok=result.ok)
    elif name == "read_file":
        state.emit(TraceEventType.FILE_READ, name=str(args.get("path")), ok=result.ok)
    else:
        state.emit(TraceEventType.TOOL_RESULT, name=name, ok=result.ok)
