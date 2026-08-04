"""Explicit adapter registry; construction has no hidden global provider state."""

from __future__ import annotations

from codeagent_eval.adapters.base import AgentAdapter
from codeagent_eval.adapters.claude_code import ClaudeCodeAdapter, ClaudeCodeConfig
from codeagent_eval.adapters.mini_agent import MiniAgentAdapter

ADAPTER_NAMES = ("mini_agent", "claude_code")

#: Adapters that drive a separate coding-agent process. They ignore ``provider``/``harness``
#: (the framework owns its own model client) and the runner treats their name as the agent
#: label, instead of folding them into the V1/V2 harness axis.
EXTERNAL_ADAPTERS = ("claude_code",)


def create_adapter(
    name: str,
    *,
    provider=None,
    harness: str = "v2",
    max_completion_tokens: int = 2048,
    config=None,
    ablate: frozenset[str] = frozenset(),
    context_budget_tokens: int = 32_000,
) -> AgentAdapter:
    """Build an adapter by name.

    ``config`` is the adapter-specific settings object (e.g. :class:`ClaudeCodeConfig`);
    it is rejected rather than ignored when an adapter has no use for it, so a typo in an
    experiment definition fails loudly instead of silently running unconfigured.
    """
    if name == "mini_agent":
        if config is not None:
            raise ValueError("mini_agent takes no adapter config; pass provider/harness instead")
        return MiniAgentAdapter(
            provider,
            harness=harness,
            max_completion_tokens=max_completion_tokens,
            ablate=ablate,
            context_budget_tokens=context_budget_tokens,
        )
    if name == "claude_code":
        if config is not None and not isinstance(config, ClaudeCodeConfig):
            raise TypeError("claude_code requires a ClaudeCodeConfig")
        return ClaudeCodeAdapter(config)
    raise ValueError(f"unknown adapter {name!r}; available: {', '.join(ADAPTER_NAMES)}")
