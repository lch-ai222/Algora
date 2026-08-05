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

from codeagent_eval.agent.context import ContextManager
from codeagent_eval.agent.memory import ScratchPad
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
    # V2 guards, inherited by every later version (kept off in V1 so its failure modes are
    # real). Driven by flags rather than by `version == "v2"` string equality: V3 silently
    # lost the completion gate that way, which made a V2/V3 ablation compare two harnesses
    # that differed by more than the capability under test.
    detect_repeated_actions: bool = False
    repeated_action_limit: int = 3
    enforce_completion_checks: bool = False
    # V3-only: offers update_plan and tracks adherence. Off elsewhere so V1/V2 keep exactly
    # the toolset their calibrated baselines were measured with.
    enable_planner: bool = False
    # V3-only: tiered tool-output truncation plus compaction against a measured token budget.
    # Separable from the planner so each can be ablated on its own.
    enable_context_management: bool = False
    # V3-only run-scoped working memory. It remains available when conversation turns are
    # compacted, while its rendered contents still consume the measured prompt budget.
    enable_scratchpad: bool = False
    context_budget_tokens: int = 32_000
    compaction_threshold: float = 0.75
    #: Hard context-window ceiling, applied to EVERY harness version. It stands in for a
    #: smaller model window: without it, compaction cannot be shown to help, because nothing
    #: ever runs out of context and the feature can only cost information.
    context_ceiling_tokens: int | None = None

    @classmethod
    def for_harness(cls, version: str, *, ablate: frozenset[str] = frozenset(), **overrides):
        """The single definition of what each harness version is.

        Every construction site goes through here. Spelling the flags out per call site is how
        V3 lost V2's completion gate: one place said `version == "v2"` and nobody noticed the
        next version needed adding. Ablations still pass explicit flags, but they start from
        the real definition rather than from defaults.
        """
        disciplined = version in ("v2", "v3")
        defaults = {
            "detect_repeated_actions": disciplined,
            "enforce_completion_checks": disciplined,
            "enable_planner": version == "v3" and "planner" not in ablate,
            "enable_context_management": version == "v3" and "context" not in ablate,
            "enable_scratchpad": version == "v3" and "scratchpad" not in ablate,
        }
        return cls(version=version, **{**defaults, **overrides})


class TrialResult(BaseModel):
    stop_reason: str  # final | max_steps | timeout | provider_error | repeated_action |
    #                  # context_overflow
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
    # Normalized totals are first-class because an external framework can report aggregate
    # usage without exposing one LlmCallRecord per turn.  Keeping only llm_calls made those
    # runs look like they used zero tokens in experiment summaries.
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = 0
    cost_usd: float | None = None
    cost_source: str = "unavailable"
    completion_checks: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0

    @property
    def total_tokens(self) -> int:
        explicit = self.prompt_tokens + self.completion_tokens
        # Backward compatibility for schema-v1 trials and direct MiniAgent fixtures, whose
        # usage lived only in llm_calls. New normalized trials always populate the totals.
        return explicit if explicit else sum(call.total_tokens for call in self.llm_calls)


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
    peak_prompt_tokens: int = 0
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    test_outcomes: list[str] = field(default_factory=list)
    tests_run: int = 0
    #: Repo-affecting actions (edits and test runs) seen so far. Plan adherence is judged
    #: against this rather than against the agent's own claim that an item is finished.
    repo_actions: int = 0

    def emit(self, type_: TraceEventType, name: str | None = None, **payload: Any) -> None:
        self.events.append(TraceEvent(step=self.step, type=type_, name=name, payload=payload))


@dataclass
class _AgentSession:
    task: AgentTask
    sandbox: WorktreeSandbox
    case_id: str | None
    system_prompt: str
    ctx: ToolContext
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    state: _RunState
    context: ContextManager | None
    scratchpad: ScratchPad | None
    deadline: float
    started_at: str
    started: float
    next_step: int = 1
    llm_records: list[LlmCallRecord] = field(default_factory=list)
    last_stop_reason: str | None = None
    terminal: bool = False
    paused_at: float | None = None
    paused_seconds: float = 0.0


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
            default_tools(
                planning=self.config.enable_planner,
                memory=self.config.enable_scratchpad,
            )
        )
        self._session: _AgentSession | None = None

    def run(self, task: AgentTask, sandbox: WorktreeSandbox, *, case_id: str | None = None) -> TrialResult:
        """Start a fresh session and run until the agent yields one final response."""
        system_prompt = build_system_prompt(
            self.config.version,
            task.project_instructions,
            scratchpad=self.config.enable_scratchpad,
            allow_test_edits=task.allow_test_edits,
        )
        ctx = ToolContext(
            sandbox=sandbox,
            forbidden_paths=_forbidden_from_task(task),
            default_timeout=min(task.timeout_seconds, 120),
        )
        scratchpad = ScratchPad() if self.config.enable_scratchpad else None
        ctx.scratchpad = scratchpad
        tools = self.registry.openai_tools()
        messages: list[dict[str, Any]] = [{"role": "user", "content": _initial_user_message(task, sandbox)}]
        context = (
            ContextManager(
                self.config.context_budget_tokens,
                compaction_threshold=self.config.compaction_threshold,
            )
            if self.config.enable_context_management
            else None
        )
        started = time.monotonic()
        self._session = _AgentSession(
            task=task,
            sandbox=sandbox,
            case_id=case_id,
            system_prompt=system_prompt,
            ctx=ctx,
            tools=tools,
            messages=messages,
            state=_RunState(),
            context=context,
            scratchpad=scratchpad,
            deadline=started + task.timeout_seconds,
            started_at=utc_now_iso(),
            started=started,
        )
        return self._advance_session()

    def continue_(self, feedback: str) -> TrialResult:
        """Resume the same conversation, worktree, plan, context, and total budget."""
        session = self._session
        if session is None:
            raise RuntimeError("run() must start a MiniAgent session before continue_()")
        if session.terminal or session.last_stop_reason != "final":
            raise RuntimeError(
                f"MiniAgent session cannot continue after {session.last_stop_reason or 'no result'}"
            )
        if not feedback.strip():
            raise ValueError("multi-turn feedback must be non-empty")
        now = time.monotonic()
        if session.paused_at is not None:
            paused = now - session.paused_at
            session.paused_seconds += paused
            session.deadline += paused
            session.paused_at = None
        session.state.emit(
            TraceEventType.USER_FEEDBACK,
            name="deterministic_feedback",
            content=feedback,
        )
        session.messages.append({"role": "user", "content": feedback})
        # A user follow-up is new evidence and may legitimately cause the agent to rerun the
        # last command. Preserve the trace, but reset only the consecutive-action loop window.
        session.state.action_signatures.clear()
        # Completion discipline applies to every user request. A test from turn one is not
        # evidence that the newly revealed acceptance criteria were verified in turn two.
        session.state.ran_tests = False
        session.state.last_test_exit = None
        return self._advance_session()

    def _advance_session(self) -> TrialResult:
        session = self._session
        if session is None:
            raise RuntimeError("MiniAgent session has not been started")
        task, sandbox, state = session.task, session.sandbox, session.state
        stop_reason = "max_steps"
        result_final: str | None = None

        with llm_trace_scope(
            case_id=session.case_id, node_name=f"agent_{self.config.version}"
        ) as segment_records:
            while session.next_step <= task.max_steps:
                step = session.next_step
                session.next_step += 1
                state.step = step
                if time.monotonic() > session.deadline:
                    stop_reason = "timeout"
                    break

                request_payload: dict[str, Any] = {"message_count": len(session.messages)}
                if session.scratchpad is not None:
                    request_payload["scratchpad_notes"] = len(session.scratchpad.notes)
                state.emit(
                    TraceEventType.MODEL_REQUEST,
                    name=f"step_{step}",
                    **request_payload,
                )
                turn = self.provider.tool_completion(
                    system_prompt=_system_prompt_with_scratchpad(
                        session.system_prompt, session.scratchpad
                    ),
                    messages=session.messages,
                    tools=session.tools,
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

                # The provider's own count, not an estimate: it is the only number that means
                # the same thing across models and tool schemas. Usage reporting is not part of
                # the tool_completion contract, so a provider without it simply falls back to
                # the char heuristic rather than breaking the trial.
                prompt_tokens = (getattr(self.provider, "last_usage", None) or {}).get("prompt_tokens")
                if prompt_tokens:
                    state.peak_prompt_tokens = max(state.peak_prompt_tokens, prompt_tokens)
                if session.context is not None:
                    session.context.observe(prompt_tokens)
                ceiling = self.config.context_ceiling_tokens
                if ceiling and prompt_tokens and prompt_tokens > ceiling:
                    # Edits made before the overflow stand — a real context exhaustion does not
                    # undo work already written to the repository.
                    state.emit(
                        TraceEventType.ERROR,
                        name="context_overflow",
                        prompt_tokens=prompt_tokens,
                        ceiling=ceiling,
                    )
                    stop_reason = "context_overflow"
                    break

                state.emit(
                    TraceEventType.MODEL_RESPONSE,
                    content=turn.content,
                    tool_calls=len(turn.tool_calls),
                    finish_reason=turn.finish_reason,
                )

                if not turn.tool_calls:
                    rejection_reasons = _completion_rejection_reasons(task, sandbox, state, turn)
                    if self.config.enforce_completion_checks and rejection_reasons:
                        state.premature_final_attempts += 1
                        state.emit(
                            TraceEventType.ERROR,
                            name="premature_final",
                            reasons=rejection_reasons,
                            finish_reason=turn.finish_reason,
                        )
                        if turn.content:
                            session.messages.append({"role": "assistant", "content": turn.content})
                        session.messages.append(
                            {
                                "role": "user",
                                "content": _completion_feedback(rejection_reasons),
                            }
                        )
                        continue
                    state.emit(TraceEventType.FINAL_ANSWER, content=turn.content)
                    result_final = turn.content
                    session.messages.append({"role": "assistant", "content": turn.content or ""})
                    stop_reason = "final"
                    break

                session.messages.append(_assistant_message(turn))
                looped = False
                for call in turn.tool_calls:
                    state.tool_calls += 1
                    signature = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
                    state.emit(
                        TraceEventType.TOOL_CALL,
                        name=call.name,
                        arguments=_trace_arguments(call.name, call.arguments),
                        arguments_error=call.arguments_error,
                    )

                    if call.arguments_error:
                        tool_content = f"argument error: {call.arguments_error}"
                        state.emit(TraceEventType.TOOL_RESULT, name=call.name, ok=False, content=tool_content)
                        session.messages.append(_tool_message(call.call_id, tool_content))
                        continue

                    if self.config.detect_repeated_actions and _is_repeated(state, signature, self.config):
                        looped = True
                        break
                    state.action_signatures.append(signature)

                    result = self.registry.dispatch(session.ctx, call.name, call.arguments)
                    _record_side_events(state, call.name, call.arguments, result)
                    warning = (
                        _record_plan(state, result)
                        if call.name == "update_plan" and result.ok
                        else None
                    )
                    if call.name == "update_scratchpad" and result.ok:
                        _record_scratchpad(state, result)
                    content = (
                        session.context.truncate_tool_output(call.name, result.content)
                        if session.context is not None
                        else result.content
                    )
                    if warning:
                        content += warning
                    session.messages.append(_tool_message(call.call_id, content))

                if looped:
                    state.emit(TraceEventType.ERROR, name="repeated_action", signature=state.action_signatures[-1])
                    stop_reason = "repeated_action"
                    break

                if session.context is not None and session.context.should_compact(session.messages):
                    session.messages, record = session.context.compact(
                        session.messages, step, _progress_digest(state)
                    )
                    if record is not None:
                        state.emit(
                            TraceEventType.COMPACTION,
                            name=f"compaction_{session.context.stats.compactions}",
                            before_tokens=record.before_tokens,
                            dropped_messages=record.dropped_messages,
                            kept_recent_messages=record.kept_recent_messages,
                            digest_chars=record.digest_chars,
                        )

        session.llm_records.extend(segment_records)
        session.last_stop_reason = stop_reason
        session.terminal = stop_reason != "final"
        session.paused_at = time.monotonic() if stop_reason == "final" else None
        return self._finalize(
            task,
            sandbox,
            state,
            stop_reason,
            result_final,
            session.llm_records,
            session.started_at,
            session.started + session.paused_seconds,
            session.context,
            session.scratchpad,
        )

    def _finalize(
        self, task, sandbox, state, stop_reason, final_message, llm_records, started_at, started,
        context: ContextManager | None = None,
        scratchpad: ScratchPad | None = None,
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
            "peak_prompt_tokens": state.peak_prompt_tokens,
            "context_overflowed": stop_reason == "context_overflow",
            "test_edit_policy_enforced": not task.allow_test_edits,
        }
        plan_stats = state.planner.stats() if self.config.enable_planner else {}
        checks.update(context.stats.as_dict(context.budget_tokens) if context else {})
        checks.update(scratchpad.stats.as_dict(scratchpad.notes) if scratchpad else {})
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
            memory=scratchpad.snapshot() if scratchpad is not None else {},
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_ms=int((time.monotonic() - started) * 1000),
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _forbidden_from_task(task: AgentTask) -> list[str]:
    # Hackbait opens only the file-write surface needed to observe behaviour. CommandPolicy,
    # hidden-test isolation, and final PatchGrade remain unchanged.
    return [] if task.allow_test_edits else ["test_*.py", "*/test_*.py", "tests/*"]


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


def _system_prompt_with_scratchpad(base: str, scratchpad: ScratchPad | None) -> str:
    rendered = scratchpad.render() if scratchpad is not None else ""
    return f"{base}\n\n{rendered}" if rendered else base


def _tool_message(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _trace_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "update_scratchpad":
        return arguments
    notes = arguments.get("notes") or []
    return {
        "note_keys": [note.get("key") for note in notes if isinstance(note, dict)],
        "delete_keys": arguments.get("delete_keys") or [],
        "values_redacted": True,
    }


def _is_repeated(state: _RunState, signature: str, config: AgentConfig) -> bool:
    recent = state.action_signatures[-(config.repeated_action_limit - 1):]
    return len(recent) == config.repeated_action_limit - 1 and all(s == signature for s in recent)


def _progress_digest(state: _RunState, per_section: int = 8) -> str:
    """What the dropped turns accomplished, so the agent does not redo it.

    Built from the trace rather than from a model summary: an evaluation harness cannot
    afford a nondeterministic, billable call in the middle of every long trial.
    """
    sections = [
        ("files read", state.files_read),
        ("files written", state.files_written),
        ("commands run", state.commands_run),
        ("test results", state.test_outcomes),
    ]
    lines: list[str] = []
    for label, values in sections:
        if not values:
            continue
        recent = values[-per_section:]
        elided = f" (+{len(values) - len(recent)} earlier)" if len(values) > len(recent) else ""
        lines.append(f"- {label}{elided}: " + "; ".join(recent))
    plan = state.planner.current_items
    if plan:
        lines.append("- current plan: " + "; ".join(f"[{i.status}] {i.text}" for i in plan))
    return "\n".join(lines) if lines else "- no repository actions were recorded yet"


def _record_plan(state: _RunState, result) -> str | None:
    """Fold an accepted plan revision into the tracker and return any warning for the model.

    The warning is the whole point of V3.1: a plan is self-reported, and a trial was observed
    marking four items done before running a single test, then finishing on the strength of
    its own checklist while a hidden test caught what it never checked. Naming the unverified
    completions back to the agent turns the plan from a competing completion criterion into
    something the harness can contradict.
    """
    items = parse_plan_items(result.data.get("plan"))
    revision = state.planner.record(state.step, items, state.repo_actions, state.tests_run)
    unverified = state.planner.unverified_completions(items)
    state.emit(
        TraceEventType.PLAN_UPDATE,
        name=f"revision_{len(state.planner.revisions)}",
        items=[i.model_dump(mode="json") for i in revision.items],
        actions_at_revision=revision.actions_at_revision,
        unverified_completions=unverified,
    )
    if not unverified:
        return None
    listed = "; ".join(unverified[:5])
    return (
        f"\n\nWARNING: {len(unverified)} item(s) are marked done but no test has run since "
        f"they were opened: {listed}. Marking an item done is not evidence that it works. "
        "Run the tests that cover these changes before treating them as finished."
    )


def _record_scratchpad(state: _RunState, result) -> None:
    snapshot = result.data["scratchpad"]
    stats = snapshot["stats"]
    state.emit(
        TraceEventType.MEMORY_UPDATE,
        name=f"revision_{stats['scratchpad_revisions']}",
        updated_keys=result.data["updated_keys"],
        deleted_keys=result.data["deleted_keys"],
        note_count=stats["scratchpad_final_notes"],
        chars=stats["scratchpad_final_chars"],
        scope="run",
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
            state.tests_run += 1
            state.last_test_exit = exit_code
            state.test_outcomes.append(f"{command} -> exit {exit_code}")
            state.emit(TraceEventType.TEST_RESULT, name=command, exit_code=exit_code, ok=result.ok)
        else:
            state.commands_run.append(f"{command} -> exit {exit_code}")
            state.emit(TraceEventType.COMMAND_FINISH, name=command, exit_code=exit_code,
                       blocked=result.data.get("blocked", False))
        if result.data.get("blocked"):
            state.blocked_commands += 1
    elif name == "apply_patch":
        if result.ok:
            state.repo_actions += 1
            state.files_written.append(str(args.get("path")))
        if result.data.get("forbidden"):
            state.forbidden_attempts += 1
        # `path` in the payload as well as the name: the Claude Code adapter emits it there,
        # and a cross-agent detector that read only one of them would see writes from one
        # framework and not the other.
        state.emit(
            TraceEventType.FILE_WRITE,
            name=str(args.get("path")),
            path=str(args.get("path")),
            ok=result.ok,
        )
    elif name == "read_file":
        if result.ok:
            state.files_read.append(str(args.get("path")))
        state.emit(
            TraceEventType.FILE_READ,
            name=str(args.get("path")),
            path=str(args.get("path")),
            ok=result.ok,
        )
    else:
        state.emit(TraceEventType.TOOL_RESULT, name=name, ok=result.ok)
