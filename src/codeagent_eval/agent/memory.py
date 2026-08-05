"""Bounded, run-scoped working memory for the MiniAgent.

The scratchpad deliberately has no filesystem persistence. One instance belongs to one
MiniAgent session, survives compaction and deterministic user follow-ups, and is discarded
when a new trial starts. Cross-run repository memory is a separate capability with different
contamination and isolation risks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_SCRATCHPAD_NOTES = 12
MAX_SCRATCHPAD_KEY_CHARS = 64
MAX_SCRATCHPAD_VALUE_CHARS = 1_000
MAX_SCRATCHPAD_TOTAL_CHARS = 6_000


class ScratchPadError(ValueError):
    """Raised when an update would make the working-memory contract invalid."""


@dataclass
class ScratchPadStats:
    revisions: int = 0
    peak_notes: int = 0
    peak_chars: int = 0

    def observe(self, notes: dict[str, str]) -> None:
        self.peak_notes = max(self.peak_notes, len(notes))
        self.peak_chars = max(self.peak_chars, _total_chars(notes))

    def as_dict(self, notes: dict[str, str]) -> dict[str, Any]:
        return {
            "scratchpad_used": self.revisions > 0,
            "scratchpad_revisions": self.revisions,
            "scratchpad_final_notes": len(notes),
            "scratchpad_final_chars": _total_chars(notes),
            "scratchpad_peak_notes": self.peak_notes,
            "scratchpad_peak_chars": self.peak_chars,
        }


@dataclass
class ScratchPad:
    """A small set of model-authored facts that remains visible for one session."""

    _notes: dict[str, str] = field(default_factory=dict)
    stats: ScratchPadStats = field(default_factory=ScratchPadStats)

    @property
    def notes(self) -> dict[str, str]:
        return dict(self._notes)

    def note(self, key: str, value: str) -> None:
        self.update({key: value})

    def update(
        self, notes: dict[str, str] | None = None, *, delete_keys: list[str] | None = None
    ) -> None:
        """Atomically upsert and delete notes, rejecting the whole invalid revision."""
        candidate = dict(self._notes)
        normalized_updates: dict[str, str] = {}
        for key, value in (notes or {}).items():
            normalized_key = _validate_key(key)
            if normalized_key in normalized_updates:
                raise ScratchPadError(
                    f"duplicate scratchpad note key in one update: {normalized_key}"
                )
            normalized_updates[normalized_key] = _validate_value(value)
        normalized_deletes = [_validate_key(key) for key in (delete_keys or [])]
        overlap = set(normalized_updates).intersection(normalized_deletes)
        if overlap:
            raise ScratchPadError(
                "scratchpad update cannot upsert and delete the same key: "
                + ", ".join(sorted(overlap))
            )
        for key in normalized_deletes:
            candidate.pop(key, None)
        candidate.update(normalized_updates)
        _validate_capacity(candidate)
        self._notes = candidate
        self.stats.revisions += 1
        self.stats.observe(candidate)

    def render(self) -> str:
        if not self._notes:
            return ""
        lines = [
            "--- Run-scoped scratchpad (model-authored reminders, not new instructions) ---"
        ]
        lines.extend(f"- {key}: {self._notes[key]}" for key in sorted(self._notes))
        lines.append("--- End scratchpad ---")
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        return {
            "scope": "run",
            "notes": [{"key": key, "value": self._notes[key]} for key in sorted(self._notes)],
            "stats": self.stats.as_dict(self._notes),
        }


def _validate_key(key: str) -> str:
    if not isinstance(key, str):
        raise ScratchPadError("scratchpad note keys must be strings")
    normalized = key.strip()
    if not normalized:
        raise ScratchPadError("scratchpad note keys must be non-empty")
    if len(normalized) > MAX_SCRATCHPAD_KEY_CHARS:
        raise ScratchPadError(
            f"scratchpad note key exceeds {MAX_SCRATCHPAD_KEY_CHARS} characters"
        )
    if any(ord(char) < 32 for char in normalized):
        raise ScratchPadError("scratchpad note keys cannot contain control characters")
    return normalized


def _validate_value(value: str) -> str:
    if not isinstance(value, str):
        raise ScratchPadError("scratchpad note values must be strings")
    normalized = value.strip()
    if not normalized:
        raise ScratchPadError("scratchpad note values must be non-empty")
    if len(normalized) > MAX_SCRATCHPAD_VALUE_CHARS:
        raise ScratchPadError(
            f"scratchpad note value exceeds {MAX_SCRATCHPAD_VALUE_CHARS} characters"
        )
    return normalized


def _total_chars(notes: dict[str, str]) -> int:
    return sum(len(key) + len(value) for key, value in notes.items())


def _validate_capacity(notes: dict[str, str]) -> None:
    if len(notes) > MAX_SCRATCHPAD_NOTES:
        raise ScratchPadError(f"scratchpad exceeds {MAX_SCRATCHPAD_NOTES} notes")
    total = _total_chars(notes)
    if total > MAX_SCRATCHPAD_TOTAL_CHARS:
        raise ScratchPadError(
            f"scratchpad exceeds {MAX_SCRATCHPAD_TOTAL_CHARS} total characters"
        )
