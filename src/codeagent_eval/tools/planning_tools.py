"""The ``update_plan`` tool: the agent's own view of what it intends to do.

The tool only validates and echoes. It deliberately holds no state — the loop owns the
:class:`~codeagent_eval.agent.planner.PlanTracker`, because adherence has to be judged against
repository actions the tool cannot see. Keeping the two apart means a tool call can never
quietly improve the agent's own planning score.
"""

from __future__ import annotations

from typing import Any

from codeagent_eval.agent.planner import (
    MAX_PLAN_ITEMS,
    PlanItemStatus,
    PlanValidationError,
    parse_plan_items,
)
from codeagent_eval.tools.base import Tool, ToolContext, ToolResult

_STATUS_MARK = {
    PlanItemStatus.PENDING: "[ ]",
    PlanItemStatus.IN_PROGRESS: "[~]",
    PlanItemStatus.DONE: "[x]",
    PlanItemStatus.DROPPED: "[-]",
}


class UpdatePlanTool(Tool):
    name = "update_plan"
    description = (
        "Record or revise your task plan. Send the COMPLETE list every time — it replaces the "
        "previous plan rather than appending to it. Mark an item done only after the change it "
        "describes is actually in the repository."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "plan": {
                "type": "array",
                "description": f"The full plan, at most {MAX_PLAN_ITEMS} items.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Stable id, reused across revisions."},
                        "text": {"type": "string", "description": "One concrete step."},
                        "status": {
                            "type": "string",
                            "enum": [s.value for s in PlanItemStatus],
                            "description": "pending | in_progress | done | dropped",
                        },
                    },
                    "required": ["id", "text", "status"],
                },
            }
        },
        "required": ["plan"],
    }

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        try:
            items = parse_plan_items(kwargs.get("plan"))
        except PlanValidationError as exc:
            # Returned as a normal tool result, not raised: the loop treats a malformed plan as
            # something the model can fix on the next turn, not as a trial-ending error.
            return ToolResult(ok=False, content=f"invalid plan: {exc}", data={"plan_error": str(exc)})

        rendered = "\n".join(f"{_STATUS_MARK[i.status]} {i.id}: {i.text}" for i in items)
        open_count = sum(1 for i in items if i.status in (PlanItemStatus.PENDING, PlanItemStatus.IN_PROGRESS))
        return ToolResult(
            ok=True,
            content=f"plan updated ({len(items)} items, {open_count} still open):\n{rendered}",
            data={"plan": [i.model_dump(mode="json") for i in items]},
        )
