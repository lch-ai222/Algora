"""Agent adapter contracts and built-in implementations."""

from codeagent_eval.adapters.base import (
    AgentAdapter,
    AgentRunResult,
    BudgetContract,
    Capability,
    ProbeResult,
    UnsupportedCapability,
)
from codeagent_eval.adapters.mini_agent import MiniAgentAdapter
from codeagent_eval.adapters.registry import ADAPTER_NAMES, create_adapter

__all__ = [
    "ADAPTER_NAMES",
    "AgentAdapter",
    "AgentRunResult",
    "BudgetContract",
    "Capability",
    "MiniAgentAdapter",
    "ProbeResult",
    "UnsupportedCapability",
    "create_adapter",
]
