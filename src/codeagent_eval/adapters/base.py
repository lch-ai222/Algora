"""Stable contracts shared by in-process and external coding-agent adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.models import AgentTask, LlmCallRecord, TraceEvent


class Capability(StrEnum):
    PLANNING = "planning"
    WORKING_MEMORY = "working_memory"
    MEMORY = "memory"
    COMPACTION = "compaction"
    MULTI_TURN = "multi_turn"
    SUBAGENT = "subagent"
    NATIVE_COST = "native_cost"


@dataclass(frozen=True)
class BudgetContract:
    """Comparable hard limits; adapters must reject limits they cannot enforce."""

    max_wall_clock_s: int
    max_cost_usd: float | None = None
    max_steps: int | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_wall_clock_s <= 0:
            raise ValueError("max_wall_clock_s must be positive")
        if self.max_cost_usd is not None and self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be positive when set")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("max_steps must be positive when set")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive when set")


class ProbeResult(BaseModel):
    adapter: str
    available: bool
    version: str
    detail: str | None = None


CanonicalStopReason = Literal[
    "final",
    "budget_time",
    "budget_cost",
    "budget_steps",
    "budget_context",
    "error",
    "blocked",
]
CostSource = Literal["native", "derived", "unavailable"]


class AgentRunResult(BaseModel):
    """Normalized result without discarding the framework-native diagnostic fields."""

    adapter: str
    adapter_version: str
    patch: str = ""
    changed_files: list[str] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    native_trajectory_path: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_source: CostSource = "unavailable"
    stop_reason: CanonicalStopReason
    native_stop_reason: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    budget: BudgetContract
    env_manifest: dict[str, Any] = Field(default_factory=dict)

    # Compatibility/diagnostic fields required by the existing graders and console.
    steps: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    final_message: str | None = None
    llm_calls: list[LlmCallRecord] = Field(default_factory=list)
    completion_checks: dict[str, Any] = Field(default_factory=dict)
    #: The agent's own task plan plus its adherence stats, when the framework exposes one.
    #: Empty for frameworks without a planner, which is distinct from a planner that produced
    #: nothing — the capability set says which case applies.
    plan: dict[str, Any] = Field(default_factory=dict)
    #: Run-scoped working-memory snapshot when the framework exposes one. This is separate
    #: from Capability.MEMORY, which denotes persistence across runs/tasks.
    memory: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @model_validator(mode="after")
    def validate_cost_provenance(self) -> AgentRunResult:
        if self.cost_source == "unavailable" and self.cost_usd is not None:
            raise ValueError("cost_usd must be null when cost_source is unavailable")
        if self.cost_source != "unavailable" and self.cost_usd is None:
            raise ValueError("cost_usd is required for native or derived cost")
        return self

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_trial_result(self) -> TrialResult:
        """Convert to the stable V1/V2 grading contract without losing native stop semantics."""
        fallback = {
            "budget_time": "timeout",
            "budget_steps": "max_steps",
            "budget_context": "context_overflow",
            "budget_cost": "timeout",
            "error": "provider_error",
            "blocked": "repeated_action",
            "final": "final",
        }
        return TrialResult(
            stop_reason=self.native_stop_reason or fallback[self.stop_reason],
            canonical_stop_reason=self.stop_reason,
            steps=self.steps,
            tool_call_count=self.tool_call_count,
            final_message=self.final_message,
            patch=self.patch,
            changed_files=self.changed_files,
            events=self.events,
            llm_calls=self.llm_calls,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cached_tokens=self.cached_tokens,
            cost_usd=self.cost_usd,
            cost_source=self.cost_source,
            completion_checks=self.completion_checks,
            plan=self.plan,
            memory=self.memory,
            started_at=self.started_at,
            finished_at=self.finished_at,
            duration_ms=self.duration_ms,
        )


class UnsupportedCapability(RuntimeError):
    """Raised when a requested comparison contract cannot be enforced by an adapter."""


@runtime_checkable
class AgentAdapter(Protocol):
    name: str
    adapter_version: str

    def probe(self) -> ProbeResult: ...

    def capabilities(self) -> set[Capability]: ...

    def prepare(
        self,
        workdir: Path,
        task: AgentTask,
        budget: BudgetContract,
        *,
        runtime: object | None = None,
    ) -> None: ...

    def run(self, instruction: str) -> AgentRunResult: ...

    def continue_(self, feedback: str) -> AgentRunResult: ...

    def cleanup(self) -> None: ...
