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

import re
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


def item_key(text: str) -> str:
    """Identity of a plan item.

    Deliberately the normalized text, not the model-supplied id. Models rename ids freely
    between revisions while keeping the wording identical — observed in a real trial where
    every id changed (models->records, inventory->restock, ...) and every text stayed
    byte-identical. Keying on the id made those items look brand-new and already done, which
    silently scored adherence as zero. If the text changes too, it genuinely is another item.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


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
        #: Action and test counts observed the last time an item was seen open. An item that
        #: reaches ``done`` at the same count did no work in between.
        self._open_at: dict[str, int] = {}
        self._open_at_tests: dict[str, int] = {}
        self._done_without_action: set[str] = set()
        self._done_with_action: set[str] = set()
        #: Completed without a test run since the item was opened: the change may be present
        #: but nothing checked it. This is the behaviour that lets a plan stand in for
        #: verification, so it is tracked separately from whether any edit happened.
        self._done_unverified: set[str] = set()
        #: Items whose very first appearance is already ``done``. Legitimate as bookkeeping,
        #: but it is not planning, so it is reported apart from adherence rather than counted.
        self._retroactive: set[str] = set()
        #: How often the model reissued the same item text under a new id — a real behaviour
        #: worth reporting rather than silently absorbing.
        self.id_renames = 0
        self._label: dict[str, str] = {}

    @property
    def declared(self) -> bool:
        return bool(self.revisions)

    @property
    def current_items(self) -> list[PlanItem]:
        return list(self.revisions[-1].items) if self.revisions else []

    def record(
        self, step: int, items: list[PlanItem], actions_so_far: int, tests_so_far: int = 0
    ) -> PlanRevision:
        known = (
            self._open_at.keys() | self._done_with_action | self._done_without_action
            | self._retroactive
        )
        for item in items:
            key = item_key(item.text)
            if self._label.get(key, item.id) != item.id:
                self.id_renames += 1
            self._label[key] = item.id

            if item.status in OPEN_STATUSES:
                self._open_at[key] = actions_so_far
                self._open_at_tests[key] = tests_so_far
                # Reopening a completed item withdraws the earlier completion.
                self._done_with_action.discard(key)
                self._done_without_action.discard(key)
                self._done_unverified.discard(key)
            elif item.status is PlanItemStatus.DONE:
                if key not in known:
                    self._retroactive.add(key)
                elif key in self._open_at:
                    opened_at = self._open_at.pop(key)
                    opened_at_tests = self._open_at_tests.pop(key, 0)
                    target = (
                        self._done_with_action if actions_so_far > opened_at
                        else self._done_without_action
                    )
                    target.add(key)
                    if tests_so_far <= opened_at_tests:
                        self._done_unverified.add(key)

        revision = PlanRevision(step=step, items=items, actions_at_revision=actions_so_far)
        self.revisions.append(revision)
        return revision

    def unverified_completions(self, items: list[PlanItem]) -> list[str]:
        """Items in this revision marked done with no test run since they were opened."""
        return [
            i.text for i in items
            if i.status is PlanItemStatus.DONE and item_key(i.text) in self._done_unverified
        ]

    def stats(self) -> dict[str, Any]:
        """Trajectory-derived planning metrics, safe to compute on an empty plan."""
        items = self.current_items
        total = len(items)
        open_items = [i for i in items if i.status in OPEN_STATUSES]
        done_items = [i for i in items if i.status is PlanItemStatus.DONE]
        backed = len([i for i in done_items if item_key(i.text) in self._done_with_action])
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
            "plan_done_without_action": len(
                [i for i in done_items if item_key(i.text) in self._done_without_action]
            ),
            "plan_done_retroactively": len(
                [i for i in done_items if item_key(i.text) in self._retroactive]
            ),
            # Completed with no test in between: the plan stood in for verification.
            "plan_done_unverified": len(
                [i for i in done_items if item_key(i.text) in self._done_unverified]
            ),
            "plan_id_renames": self.id_renames,
            # Items still open when the trial ended: the agent stopped mid-plan.
            "plan_abandonment": round(len(open_items) / total, 4) if total else None,
        }


class PlanSnapshot(BaseModel):
    """Persisted alongside the trial so a plan can be reviewed without replaying the trace."""

    items: list[PlanItem] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
