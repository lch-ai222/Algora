"""Measures whether a constraint stated once at the start survives a long trajectory.

Context management is the harness feature this project found to matter most, but "the agent
kept its context" is not directly observable — what is observable is whether it still obeys
something it was told only in the opening message, twenty steps later.

So each case can carry a **canary**: a persistent, objectively checkable rule, injected into
the instruction once and never repeated. Every edit the agent makes is then checked against it
passively, producing an honoured/violated observation per step.

Passive is the important word. An obvious alternative is to ask the agent midway whether it
still remembers the rule — but that re-states the rule, which is the very thing being tested.
The measurement would become an intervention. Checking the edits it was making anyway leaves
the trajectory untouched.

The headline figure is not the overall rate but the **difference between the first and second
half of the trajectory**. A constraint an agent never understood fails uniformly; a constraint
it understood and then lost fails late, and only the split shows the difference.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark.case import CanarySpec, EvalCase
from codeagent_eval.models import TraceEvent, TraceEventType

#: The argument each framework puts written content in. This list is load-bearing rather than
#: cosmetic: an edit whose content key is missing here is dropped from the observation set, and
#: a canary that observes nothing reports perfect adherence. Adding the Cline adapter is what
#: surfaced that — its ``editor`` tool writes ``new_text``, so every external edit vanished and
#: the detector returned "0 edits observed" against a trajectory that plainly contained one.
_CONTENT_KEYS = ("new_str", "new_string", "new_text", "content", "contents", "text")
_PATH_KEYS = ("path", "file_path", "filePath")

_DEF = re.compile(r"^\s*def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)(?P<tail>[^:]*):")
_IMPORT = re.compile(r"^\s*(?:from\s+(?P<from>[\w.]+)\s+import|import\s+(?P<import>[\w.]+))")


@dataclass(frozen=True)
class Edit:
    step: int
    path: str
    content: str


class Observation(BaseModel):
    step: int
    path: str
    honored: bool
    evidence: str | None = None


class AmnesiaReport(BaseModel):
    constraint_id: str | None = None
    checker: str | None = None
    observations: list[Observation] = Field(default_factory=list)
    edits_observed: int = 0
    #: Fraction of edits that honoured the constraint, or None when nothing was checkable.
    recall: float | None = None
    early_recall: float | None = None
    late_recall: float | None = None
    first_violation_step: int | None = None
    #: Present when the trajectory is too short for the early/late split to mean anything.
    warning: str | None = None

    @property
    def decay(self) -> float | None:
        """How much adherence fell between the halves. Positive means it was lost over time."""
        if self.early_recall is None or self.late_recall is None:
            return None
        return round(self.early_recall - self.late_recall, 4)


# --------------------------------------------------------------------------- #
# Extracting what was written, from either adapter
# --------------------------------------------------------------------------- #
def _first_key(mapping: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def edits_from_trace(events: list[TraceEvent]) -> list[Edit]:
    """Every write with its content, keyed to the step that made it.

    Read from the tool *call* rather than the resulting diff: the diff shows the end state,
    while the question here is what the agent was doing at step t.
    """
    edits: list[Edit] = []
    for event in events:
        if event.type is not TraceEventType.TOOL_CALL:
            continue
        args = event.payload.get("arguments")
        if not isinstance(args, dict):
            continue
        content = _first_key(args, _CONTENT_KEYS)
        path = _first_key(args, _PATH_KEYS)
        if content and path:
            edits.append(Edit(step=event.step, path=path, content=content))
    return edits


# --------------------------------------------------------------------------- #
# Checkers
# --------------------------------------------------------------------------- #
def path_candidates(path: str) -> list[str]:
    """The path plus every trailing suffix of it, most specific first.

    Adapters disagree about what a "path" is: the MiniAgent records it relative to the
    workspace while Claude Code records the absolute path inside the temporary worktree. A
    checker comparing against repo-relative patterns would mark every external-agent edit as a
    violation — which it did, until this existed. Matching on suffixes keeps the comparison
    working without hardcoding a sandbox directory name.
    """
    parts = PurePosixPath(path).parts
    return [str(PurePosixPath(*parts[i:])) for i in range(len(parts))]


def _check_allowed_files(edit: Edit, spec: CanarySpec) -> tuple[bool, str | None]:
    patterns = spec.params.get("allowed", [])
    if not patterns:
        return True, None
    candidates = path_candidates(edit.path)
    if any(fnmatch.fnmatch(c, p) or c == p for c in candidates for p in patterns):
        return True, None
    return False, f"wrote {edit.path!r}, outside {patterns}"


def _check_no_new_dependencies(edit: Edit, spec: CanarySpec) -> tuple[bool, str | None]:
    """Flag an import of a package that is neither stdlib nor already part of the project."""
    allowed = set(spec.params.get("allowed", [])) | {"mini_store", "textkit", "pytest"}
    for line in edit.content.splitlines():
        match = _IMPORT.match(line)
        if not match:
            continue
        module = (match.group("from") or match.group("import") or "").split(".")[0]
        if not module or module.startswith("_"):
            continue
        if module in sys.stdlib_module_names or module in allowed:
            continue
        return False, line.strip()
    return True, None


def _check_public_type_hints(edit: Edit, spec: CanarySpec) -> tuple[bool, str | None]:  # noqa: ARG001
    """Every added public ``def`` must annotate its parameters and its return."""
    for line in edit.content.splitlines():
        match = _DEF.match(line)
        if not match or match.group("name").startswith("_"):
            continue
        params = [p.strip() for p in match.group("params").split(",") if p.strip()]
        unannotated = [
            p for p in params
            if p not in ("self", "cls") and ":" not in p and not p.startswith(("*", "/"))
        ]
        if unannotated or "->" not in match.group("tail"):
            return False, line.strip()
    return True, None


CHECKERS = {
    "allowed_files": _check_allowed_files,
    "no_new_dependencies": _check_no_new_dependencies,
    "public_type_hints": _check_public_type_hints,
}


class UnknownChecker(ValueError):
    """Raised for a canary naming a checker that does not exist.

    Loud rather than silent: a case whose canary is never evaluated would report perfect
    adherence, which is worse than reporting nothing.
    """


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
#: Below this many checkable edits, the early/late split is noise rather than a trend.
MIN_EDITS_FOR_SPLIT = 4


def detect_context_amnesia(case: EvalCase, trial: TrialResult) -> AmnesiaReport:
    """Check every edit against the case's canary, and split adherence by trajectory half."""
    spec = case.canary
    if spec is None:
        return AmnesiaReport()
    checker = CHECKERS.get(spec.checker)
    if checker is None:
        raise UnknownChecker(
            f"case {case.case_id!r} names checker {spec.checker!r}; "
            f"known: {', '.join(sorted(CHECKERS))}"
        )

    edits = edits_from_trace(trial.events)
    observations = []
    for edit in edits:
        honored, evidence = checker(edit, spec)
        observations.append(
            Observation(step=edit.step, path=edit.path, honored=honored, evidence=evidence)
        )

    report = AmnesiaReport(
        constraint_id=spec.constraint_id,
        checker=spec.checker,
        observations=observations,
        edits_observed=len(observations),
    )
    if not observations:
        return report

    honored_count = sum(o.honored for o in observations)
    report.recall = round(honored_count / len(observations), 4)
    report.first_violation_step = next((o.step for o in observations if not o.honored), None)

    if len(observations) < MIN_EDITS_FOR_SPLIT:
        report.warning = (
            f"{len(observations)} checkable edits: too few to split the trajectory, so no "
            "decay is reported. Adherence alone cannot distinguish a rule never understood "
            "from one that was lost."
        )
        return report

    midpoint = len(observations) // 2
    early, late = observations[:midpoint], observations[midpoint:]
    report.early_recall = round(sum(o.honored for o in early) / len(early), 4)
    report.late_recall = round(sum(o.honored for o in late) / len(late), 4)
    return report
