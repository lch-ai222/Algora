"""Tool abstraction + registry for the MiniAgent.

Mirrors ft_diag_agent's ``ToolRegistry`` shape (register / dispatch), but the tools here
act on a ``WorktreeSandbox``. Each tool declares an OpenAI-compatible JSON schema so the
provider can offer it, and returns a ``ToolResult`` whose ``content`` is fed back to the
model as the tool message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from codeagent_eval.sandbox.worktree import WorktreeSandbox

if TYPE_CHECKING:
    from codeagent_eval.agent.memory import ScratchPad


@dataclass
class ToolContext:
    """Per-trial execution context shared by all tools."""

    sandbox: WorktreeSandbox
    forbidden_paths: list[str] = field(default_factory=list)  # fnmatch globs, relative to workspace
    default_timeout: int = 120
    page_size: int = 200
    scratchpad: ScratchPad | None = None


class ToolResult(BaseModel):
    ok: bool
    content: str  # text returned to the model
    data: dict[str, Any] = {}  # structured extras for trace/graders (e.g. exit_code, files)


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the function's arguments

    @abstractmethod
    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def names(self) -> list[str]:
        return list(self._tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    def dispatch(self, ctx: ToolContext, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, content=f"unknown tool: {name!r}. available: {', '.join(self._tools)}")
        try:
            return tool.run(ctx, **arguments)
        except TypeError as exc:  # bad/missing arguments
            return ToolResult(ok=False, content=f"invalid arguments for {name}: {exc}")
        except Exception as exc:  # a tool bug must not crash the trial
            return ToolResult(ok=False, content=f"tool {name} raised {type(exc).__name__}: {exc}")
