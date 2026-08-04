"""Shared trajectory-normalization vocabulary for external coding-agent adapters.

Every framework names its tools differently: Claude Code has ``Read``/``Edit``/``Bash``,
the MiniAgent has ``read_file``/``apply_patch``/``run_command``, mini-swe-agent exposes a
single shell action. Detectors, graders, the failure taxonomy and the trace viewer must not
learn each framework's vocabulary, so every adapter translates native tool names into the
same :class:`~codeagent_eval.models.TraceEventType` semantics the in-process MiniAgent emits.

Only *semantics* are normalized here. Native names, arguments and raw payloads are preserved
by the adapters so a normalization mistake stays auditable against the original trajectory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codeagent_eval.models import TraceEventType


def is_test_command(command: str) -> bool:
    """Whether a shell command counts as a test run.

    Mirrors ``MiniAgent._record_side_events`` exactly. It is duplicated rather than imported
    so the calibrated V1/V2 loop stays byte-for-byte unchanged; ``test_adapters`` asserts the
    two definitions agree, which turns silent drift into a failing test.
    """
    return "pytest" in command


@dataclass(frozen=True)
class ToolSemantics:
    """Maps one framework's tool names onto normalized trace semantics.

    Names not listed in any bucket fall back to ``TOOL_RESULT``: an unrecognized tool is
    recorded as a generic action rather than guessed at or dropped.
    """

    read: frozenset[str] = field(default_factory=frozenset)
    write: frozenset[str] = field(default_factory=frozenset)
    command: frozenset[str] = field(default_factory=frozenset)
    plan: frozenset[str] = field(default_factory=frozenset)

    def classify(self, tool_name: str, command: str | None = None) -> TraceEventType:
        if tool_name in self.plan:
            return TraceEventType.PLAN_UPDATE
        if tool_name in self.read:
            return TraceEventType.FILE_READ
        if tool_name in self.write:
            return TraceEventType.FILE_WRITE
        if tool_name in self.command:
            if command and is_test_command(command):
                return TraceEventType.TEST_RESULT
            return TraceEventType.COMMAND_FINISH
        return TraceEventType.TOOL_RESULT

    def knows(self, tool_name: str) -> bool:
        return tool_name in (self.read | self.write | self.command | self.plan)


#: The in-process MiniAgent's own vocabulary, kept here so cross-adapter comparisons read
#: from one table instead of re-deriving the mapping per call site.
MINI_AGENT_SEMANTICS = ToolSemantics(
    read=frozenset({"read_file"}),
    write=frozenset({"apply_patch"}),
    command=frozenset({"run_command"}),
    plan=frozenset({"update_plan"}),
)

#: Claude Code's built-in tool names. ``ExitPlanMode`` is grouped with the planning tools
#: because it marks a plan transition, not a repository action.
CLAUDE_CODE_SEMANTICS = ToolSemantics(
    read=frozenset({"Read", "NotebookRead"}),
    write=frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"}),
    command=frozenset({"Bash", "BashOutput", "KillShell"}),
    plan=frozenset({"TodoWrite", "ExitPlanMode"}),
)
