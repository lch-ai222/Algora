"""Adapter that exposes the existing in-process MiniAgent through the V3 contract."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from codeagent_eval import __version__
from codeagent_eval.adapters.base import (
    AgentRunResult,
    BudgetContract,
    Capability,
    ProbeResult,
    UnsupportedCapability,
)
from codeagent_eval.agent.loop import AgentConfig, MiniAgent, TrialResult
from codeagent_eval.models import AgentTask
from codeagent_eval.sandbox import WorktreeSandbox

_STOP_REASON_MAP = {
    "final": "final",
    "timeout": "budget_time",
    "max_steps": "budget_steps",
    "provider_error": "error",
    "repeated_action": "blocked",
}


class MiniAgentAdapter:
    name = "mini_agent"

    def __init__(self, provider, *, harness: str = "v2", max_completion_tokens: int = 2048) -> None:
        if harness not in {"v1", "v2"}:
            raise ValueError(f"unsupported MiniAgent harness: {harness}")
        self.provider = provider
        self.harness = harness
        if max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be positive")
        self.max_completion_tokens = max_completion_tokens
        self.adapter_version = f"{__version__}+{harness}"
        self._task: AgentTask | None = None
        self._budget: BudgetContract | None = None
        self._sandbox: WorktreeSandbox | None = None

    def probe(self) -> ProbeResult:
        enabled = getattr(self.provider, "enabled", True)
        detail = None if enabled else getattr(self.provider, "_availability_error", lambda: "provider disabled")()
        return ProbeResult(
            adapter=self.name,
            available=bool(enabled),
            version=self.adapter_version,
            detail=detail,
        )

    def capabilities(self) -> set[Capability]:
        # V2 injects repository instructions, but it has no explicit planner/memory/compaction
        # subsystem and its provider cost is derived rather than natively reported.
        return set()

    def prepare(
        self,
        workdir: Path,
        task: AgentTask,
        budget: BudgetContract,
        *,
        runtime: object | None = None,
    ) -> None:
        if not isinstance(runtime, WorktreeSandbox):
            raise TypeError("MiniAgentAdapter requires a WorktreeSandbox runtime")
        if workdir.resolve() != runtime.root.resolve():
            raise ValueError("workdir and sandbox root must identify the same workspace")
        if budget.max_cost_usd is not None:
            raise UnsupportedCapability("MiniAgent cannot yet enforce a hard cost budget")
        if budget.max_tokens is not None:
            raise UnsupportedCapability("MiniAgent cannot yet enforce an aggregate token budget")

        updates = {
            "workspace_path": str(workdir),
            "timeout_seconds": min(task.timeout_seconds, budget.max_wall_clock_s),
        }
        if budget.max_steps is not None:
            updates["max_steps"] = min(task.max_steps, budget.max_steps)
        self._task = task.model_copy(update=updates)
        self._budget = budget
        self._sandbox = runtime

    def run(self, instruction: str) -> AgentRunResult:
        if self._task is None or self._budget is None or self._sandbox is None:
            raise RuntimeError("adapter must be prepared before run")
        task = self._task.model_copy(update={"instruction": instruction})
        config = AgentConfig(
            version=self.harness,
            detect_repeated_actions=self.harness == "v2",
            max_tokens=self.max_completion_tokens,
        )
        trial = MiniAgent(self.provider, config).run(task, self._sandbox, case_id=task.case_id)
        return self._normalize(trial)

    def continue_(self, feedback: str) -> AgentRunResult:  # noqa: ARG002
        raise UnsupportedCapability("MiniAgent does not support multi-turn continuation yet")

    def cleanup(self) -> None:
        self._task = None
        self._budget = None
        self._sandbox = None

    def _normalize(self, trial: TrialResult) -> AgentRunResult:
        prompt_tokens = sum(call.prompt_tokens for call in trial.llm_calls)
        completion_tokens = sum(call.completion_tokens for call in trial.llm_calls)
        cost = sum(call.estimated_cost_usd for call in trial.llm_calls)
        settings = getattr(self.provider, "settings", None)
        pricing_configured = bool(
            settings
            and (
                getattr(settings, "llm_prompt_cost_per_1k_usd", 0) > 0
                or getattr(settings, "llm_completion_cost_per_1k_usd", 0) > 0
            )
        )
        cost_available = bool(trial.llm_calls) and pricing_configured
        return AgentRunResult(
            adapter=self.name,
            adapter_version=self.adapter_version,
            patch=trial.patch,
            changed_files=trial.changed_files,
            events=trial.events,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=0,
            cost_usd=cost if cost_available else None,
            cost_source="derived" if cost_available else "unavailable",
            stop_reason=_STOP_REASON_MAP.get(trial.stop_reason, "error"),
            native_stop_reason=trial.stop_reason,
            duration_ms=trial.duration_ms,
            budget=self._budget,
            env_manifest={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "repo_commit": _git_head(self._sandbox.root),
                "harness": self.harness,
            },
            steps=trial.steps,
            tool_call_count=trial.tool_call_count,
            final_message=trial.final_message,
            llm_calls=trial.llm_calls,
            completion_checks=trial.completion_checks,
            started_at=trial.started_at,
            finished_at=trial.finished_at,
        )


def _git_head(workdir: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None
