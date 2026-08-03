"""Explicit adapter registry; construction has no hidden global provider state."""

from __future__ import annotations

from codeagent_eval.adapters.base import AgentAdapter
from codeagent_eval.adapters.mini_agent import MiniAgentAdapter

ADAPTER_NAMES = ("mini_agent",)


def create_adapter(
    name: str,
    *,
    provider,
    harness: str = "v2",
    max_completion_tokens: int = 2048,
) -> AgentAdapter:
    if name == "mini_agent":
        return MiniAgentAdapter(
            provider,
            harness=harness,
            max_completion_tokens=max_completion_tokens,
        )
    raise ValueError(f"unknown adapter {name!r}; available: {', '.join(ADAPTER_NAMES)}")
