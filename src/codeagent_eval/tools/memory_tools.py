"""Tool contract for the MiniAgent's run-scoped ScratchPad."""

from __future__ import annotations

from typing import Any

from codeagent_eval.agent.memory import ScratchPadError
from codeagent_eval.tools.base import Tool, ToolContext, ToolResult


class UpdateScratchpadTool(Tool):
    name = "update_scratchpad"
    description = (
        "Update run-scoped working memory with durable facts, decisions, constraints, or open "
        "questions that must survive context compaction and user follow-ups. Upserts and deletes "
        "are atomic. Keep notes concise; this is not a transcript or a task plan."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "notes": {
                "type": "array",
                "description": "Notes to add or replace by key.",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Stable, concise note key."},
                        "value": {"type": "string", "description": "Durable fact or decision."},
                    },
                    "required": ["key", "value"],
                },
            },
            "delete_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys that are stale and should be removed.",
            },
        },
    }

    def run(
        self,
        ctx: ToolContext,
        notes: list[dict[str, str]] | None = None,
        delete_keys: list[str] | None = None,
    ) -> ToolResult:
        if ctx.scratchpad is None:
            return ToolResult(ok=False, content="run-scoped scratchpad is not enabled")
        updates: dict[str, str] = {}
        try:
            for note in notes or []:
                if not isinstance(note, dict) or set(note) != {"key", "value"}:
                    raise ScratchPadError("each scratchpad note requires only key and value")
                key = note["key"]
                if key in updates:
                    raise ScratchPadError(f"duplicate scratchpad note key in one update: {key}")
                updates[key] = note["value"]
            if not updates and not delete_keys:
                raise ScratchPadError("scratchpad update must add, replace, or delete a note")
            ctx.scratchpad.update(updates, delete_keys=delete_keys)
        except (KeyError, ScratchPadError) as exc:
            return ToolResult(ok=False, content=f"invalid scratchpad update: {exc}")

        snapshot = ctx.scratchpad.snapshot()
        rendered_keys = ", ".join(note["key"] for note in snapshot["notes"]) or "(empty)"
        return ToolResult(
            ok=True,
            content=(
                f"scratchpad updated ({len(snapshot['notes'])} notes): {rendered_keys}. "
                "These notes will remain visible for this session only."
            ),
            data={
                "scratchpad": snapshot,
                "updated_keys": sorted(updates),
                "deleted_keys": sorted(delete_keys or []),
            },
        )
