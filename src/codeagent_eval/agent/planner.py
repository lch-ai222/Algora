"""Explicit task planning for the MiniAgent, and the metrics that keep it honest.

Mainstream agents expose a plan (Claude Code's TodoWrite, Cline's Plan mode) and the JD names
task planning as a core capability, so V3 gives the MiniAgent one. But a plan an agent writes
about itself is self-reported: an agent can mark every item done and finish having changed
nothing, and a naive "completed 5/5 items" metric would score that as perfect planning.

So adherence is measured against the repository, not against the agent's own claims. Each
item's transition to ``done`` is checked for an intervening repo action — a file write or a
test run. An item that goes from open to done with no action in between is recorded as
``done_without_action``: plan theatre, counted separately and excluded from adherence.

The tracker is deliberately passive. It never blocks or corrects the agent; it records what
happened so an ablation (V2 without a planner vs V3 with one) can attribute a difference.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

MAX_PLAN_ITEMS = 30
MAX_ITEM_CHARS = 200


class PlanItemStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DROPPED = "dropped"


OPEN_STATUSES = frozenset({PlanItemStatus.PENDING, PlanItemStatus.IN_PROGRESS})


class PlanItem(BaseModel):
    id: str
    text: str
    status: PlanItemStatus = PlanItemStatus.PENDING


class PlanRevision(BaseModel):
    step: int
    items: list[PlanItem]
    actions_at_revision: int


class PlanValidationError(ValueError):
    """Raised for a plan the tracker cannot interpret; the message goes back to the model."""


def parse_plan_items(raw: Any) -> list[PlanItem]:
    """Validate model-supplied plan items, with errors phrased so the model can correct them."""
    if not isinstance(raw, list) or not raw:
        raise PlanValidationError("plan must be a non-empty list of items")
    if len(raw) > MAX_PLAN_ITEMS:
        raise PlanValidationError(f"plan has {len(raw)} items; at most {MAX_PLAN_ITEMS} are allowed")

    items: list[PlanItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PlanValidationError(f"item {index} must be an object with 'id', 'text', 'status'")
        item_id = str(entry.get("id") or f"item-{index + 1}").strip()
        text = str(entry.get("text") or "").strip()
        if not text:
            raise PlanValidationError(f"item {item_id!r} has empty 'text'")
        if len(text) > MAX_ITEM_CHARS:
            text = text[:MAX_ITEM_CHARS]
        if item_id in seen:
            raise PlanValidationError(f"duplicate item id {item_id!r}; ids must be unique")
        seen.add(item_id)
        raw_status = str(entry.get("status") or PlanItemStatus.PENDING).strip().lower()
        try:
            status = PlanItemStatus(raw_status)
        except ValueError as exc:
            allowed = ", ".join(s.value for s in PlanItemStatus)
            raise PlanValidationError(
                f"item {item_id!r} has unknown status {raw_status!r}; use one of: {allowed}"
            ) from exc
        items.append(PlanItem(id=item_id, text=text, status=status))
    return items


class PlanTracker:
    """Records plan revisions and whether each completion was backed by a repo action."""

    def __init__(self) -> None:
        self.revisions: list[PlanRevision] = []
        #: Action count observed the last time an item was seen in an open state. An item that
        #: reaches ``done`` at the same count did no work in between.
        self._open_at: dict[str, int] = {}
        self._done_without_action: set[str] = set()
        self._done_with_action: set[str] = set()
        #: Items whose very first appearance is already ``done``. Legitimate as bookkeeping,
        #: but it is not planning, so it is reported apart from adherence rather than counted.
        self._retroactive: set[str] = set()

    @property
    def declared(self) -> bool:
        return bool(self.revisions)

    @property
    def current_items(self) -> list[PlanItem]:
        return list(self.revisions[-1].items) if self.revisions else []

    def record(self, step: int, items: list[PlanItem], actions_so_far: int) -> PlanRevision:
        known = self._open_at.keys() | self._done_with_action | self._done_without_action | self._retroactive
        for item in items:
            if item.status in OPEN_STATUSES:
                self._open_at[item.id] = actions_so_far
                # Reopening a completed item withdraws the earlier completion.
                self._done_with_action.discard(item.id)
                self._done_without_action.discard(item.id)
            elif item.status is PlanItemStatus.DONE:
                if item.id not in known:
                    self._retroactive.add(item.id)
                elif item.id in self._open_at:
                    opened_at = self._open_at.pop(item.id)
                    target = (
                        self._done_with_action if actions_so_far > opened_at
                        else self._done_without_action
                    )
                    target.add(item.id)

        revision = PlanRevision(step=step, items=items, actions_at_revision=actions_so_far)
        self.revisions.append(revision)
        return revision

    def stats(self) -> dict[str, Any]:
        """Trajectory-derived planning metrics, safe to compute on an empty plan."""
        items = self.current_items
        total = len(items)
        open_items = [i for i in items if i.status in OPEN_STATUSES]
        done_items = [i for i in items if i.status is PlanItemStatus.DONE]
        backed = len([i for i in done_items if i.id in self._done_with_action])
        return {
            "plan_declared": self.declared,
            "plan_revisions": len(self.revisions),
            "plan_first_step": self.revisions[0].step if self.revisions else None,
            "plan_items": total,
            "plan_items_done": len(done_items),
            "plan_items_open": len(open_items),
            "plan_items_dropped": len([i for i in items if i.status is PlanItemStatus.DROPPED]),
            # Completions the repository can corroborate, over all declared items. A plan whose
            # items are all marked done with nothing written scores 0, not 1.
            "plan_adherence": round(backed / total, 4) if total else None,
            "plan_done_without_action": len([i for i in done_items if i.id in self._done_without_action]),
            "plan_done_retroactively": len([i for i in done_items if i.id in self._retroactive]),
            # Items still open when the trial ended: the agent stopped mid-plan.
            "plan_abandonment": round(len(open_items) / total, 4) if total else None,
        }


class PlanSnapshot(BaseModel):
    """Persisted alongside the trial so a plan can be reviewed without replaying the trace."""

    items: list[PlanItem] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
