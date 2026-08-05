"""Agent adapter contracts and built-in implementations."""

from codeagent_eval.adapters.base import (
    AgentAdapter,
    AgentRunResult,
    BudgetContract,
    Capability,
    ProbeResult,
    UnsupportedCapability,
)
from codeagent_eval.adapters.claude_code import (
    ClaudeCodeAdapter,
    ClaudeCodeConfig,
    parse_stream_json,
)
from codeagent_eval.adapters.cline import CLINE_SEMANTICS, ClineAdapter, ClineConfig
from codeagent_eval.adapters.mini_agent import ABLATABLE, MiniAgentAdapter
from codeagent_eval.adapters.normalize import (
    CLAUDE_CODE_SEMANTICS,
    MINI_AGENT_SEMANTICS,
    ToolSemantics,
    is_test_command,
)
from codeagent_eval.adapters.registry import ADAPTER_NAMES, EXTERNAL_ADAPTERS, create_adapter

__all__ = [
    "CLINE_SEMANTICS",
    "ClineConfig",
    "ClineAdapter",
    "ABLATABLE",
    "ADAPTER_NAMES",
    "CLAUDE_CODE_SEMANTICS",
    "EXTERNAL_ADAPTERS",
    "MINI_AGENT_SEMANTICS",
    "AgentAdapter",
    "AgentRunResult",
    "BudgetContract",
    "Capability",
    "ClaudeCodeAdapter",
    "ClaudeCodeConfig",
    "MiniAgentAdapter",
    "ProbeResult",
    "ToolSemantics",
    "UnsupportedCapability",
    "create_adapter",
    "is_test_command",
    "parse_stream_json",
]
