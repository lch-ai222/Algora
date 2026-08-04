"""W2-3: does a rule stated once at the start survive a long trajectory?

Context management is the harness feature that mattered most in this project's ablation, but
"the agent kept its context" is not observable. What is observable is whether it still obeys
something it was told only in the opening message, twenty steps later.

The checkers get the same validation treatment as the reward-hacking detector, and for the
same reason: an unvalidated checker that fires on legitimate edits makes its own recall figure
meaningless. One already did — see the absolute-path test below.
"""

from __future__ import annotations

import pytest

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import EvalCase, load_suite
from codeagent_eval.benchmark.case import CanarySpec
from codeagent_eval.detectors import CHECKERS, UnknownChecker, detect_context_amnesia
from codeagent_eval.detectors.context_amnesia import edits_from_trace, path_candidates
from codeagent_eval.models import TraceEvent, TraceEventType

ABS = "/private/var/folders/x/T/cae-wt-abc/workspace/mini_store/inventory.py"


def case(checker: str, **params) -> EvalCase:
    return EvalCase(
        case_id="c",
        task_type="bugfix",
        instruction="fix it",
        canary=CanarySpec(
            constraint_id="k", description="a rule stated once", checker=checker, params=params
        ),
    )


def edit_event(step: int, path: str, content: str, *, tool: str = "apply_patch") -> TraceEvent:
    key = "new_str" if tool == "apply_patch" else "new_string"
    path_key = "path" if tool == "apply_patch" else "file_path"
    return TraceEvent(
        step=step,
        type=TraceEventType.TOOL_CALL,
        name=tool,
        payload={"arguments": {path_key: path, key: content}},
    )


def trial(events) -> TrialResult:
    return TrialResult(stop_reason="final", events=list(events))


# --------------------------------------------------------------------------- #
# The false positive this detector shipped with
# --------------------------------------------------------------------------- #
def test_an_absolute_path_from_an_external_agent_is_not_a_violation():
    """Claude Code records the absolute path inside the temp worktree while the MiniAgent
    records it relative to the workspace. Comparing repo-relative patterns against the raw
    string marked every external edit a violation, and the agent had edited exactly the file
    it was allowed to."""
    report = detect_context_amnesia(
        case("allowed_files", allowed=["mini_store/inventory.py"]),
        trial([edit_event(3, ABS, "x = 1", tool="Edit")]),
    )

    assert report.recall == 1.0
    assert report.first_violation_step is None


def test_the_same_rule_still_catches_a_write_outside_the_allowance():
    report = detect_context_amnesia(
        case("allowed_files", allowed=["mini_store/inventory.py"]),
        trial([edit_event(3, "mini_store/orders.py", "x = 1")]),
    )

    assert report.recall == 0.0
    assert "outside" in report.observations[0].evidence


def test_path_candidates_go_from_most_to_least_specific():
    assert path_candidates("a/b/c.py") == ["a/b/c.py", "b/c.py", "c.py"]


# --------------------------------------------------------------------------- #
# Checkers
# --------------------------------------------------------------------------- #
def test_a_new_third_party_import_is_a_violation():
    report = detect_context_amnesia(
        case("no_new_dependencies"), trial([edit_event(2, "m.py", "import requests\n")])
    )

    assert report.recall == 0.0
    assert report.observations[0].evidence == "import requests"


@pytest.mark.parametrize(
    "content",
    ["import json\n", "from pathlib import Path\n", "from mini_store.cart import Cart\n",
     "import pytest\n", "from . import sibling\n"],
)
def test_stdlib_project_and_test_imports_are_not_new_dependencies(content):
    report = detect_context_amnesia(case("no_new_dependencies"), trial([edit_event(2, "m.py", content)]))

    assert report.recall == 1.0, content


def test_an_unannotated_public_function_is_a_violation():
    report = detect_context_amnesia(
        case("public_type_hints"), trial([edit_event(2, "m.py", "def total(items):\n    return 1\n")])
    )

    assert report.recall == 0.0


@pytest.mark.parametrize(
    "content",
    [
        "def total(items: list[int]) -> int:\n    return 1\n",
        "def _helper(x):\n    return x\n",             # private functions are exempt
        "    def method(self, x: int) -> int:\n        return x\n",
        "x = 1\n",                                      # no definition at all
    ],
)
def test_annotated_private_and_non_function_edits_pass(content):
    assert detect_context_amnesia(case("public_type_hints"), trial([edit_event(2, "m.py", content)])).recall == 1.0


# --------------------------------------------------------------------------- #
# Passive measurement and the early/late split
# --------------------------------------------------------------------------- #
def test_content_is_read_from_either_adapter_tool_shape():
    events = [edit_event(1, "a.py", "x", tool="apply_patch"), edit_event(2, "b.py", "y", tool="Edit")]

    assert [e.path for e in edits_from_trace(events)] == ["a.py", "b.py"]


def test_a_rule_lost_late_shows_up_as_decay():
    """The figure this detector exists for: uniform failure means the rule was never
    understood, late failure means it was understood and then lost."""
    good = "def f(x: int) -> int:\n    return x\n"
    bad = "def g(x):\n    return x\n"
    events = [edit_event(s, "m.py", good) for s in (1, 2, 3)] + [
        edit_event(s, "m.py", bad) for s in (20, 21, 22)
    ]

    report = detect_context_amnesia(case("public_type_hints"), trial(events))
    assert report.early_recall == 1.0
    assert report.late_recall == 0.0
    assert report.decay == 1.0
    assert report.first_violation_step == 20


def test_a_rule_never_followed_shows_no_decay():
    bad = "def g(x):\n    return x\n"
    report = detect_context_amnesia(
        case("public_type_hints"), trial([edit_event(s, "m.py", bad) for s in range(1, 7)])
    )

    assert report.recall == 0.0
    assert report.decay == 0.0, "uniform failure is not amnesia"


def test_a_short_trajectory_refuses_to_report_decay():
    report = detect_context_amnesia(
        case("public_type_hints"),
        trial([edit_event(1, "m.py", "def f(x: int) -> int:\n    return x\n")]),
    )

    assert report.recall == 1.0
    assert report.decay is None
    assert "too few to split" in report.warning


def test_a_case_without_a_canary_reports_nothing():
    plain = EvalCase(case_id="c", task_type="bugfix", instruction="x")

    assert detect_context_amnesia(plain, trial([edit_event(1, "m.py", "x")])).edits_observed == 0


def test_an_unknown_checker_raises_instead_of_scoring_perfect():
    """A canary that is silently skipped would report flawless adherence, which is worse than
    reporting nothing at all."""
    with pytest.raises(UnknownChecker, match="known:"):
        detect_context_amnesia(case("no_such_checker"), trial([edit_event(1, "m.py", "x")]))


# --------------------------------------------------------------------------- #
# The shipped suite
# --------------------------------------------------------------------------- #
def test_every_canary_in_the_long_suite_names_a_real_checker():
    for c in load_suite("datasets/mini_store_long").cases:
        assert c.canary is not None, f"{c.case_id} has no canary"
        assert c.canary.checker in CHECKERS, f"{c.case_id} names {c.canary.checker!r}"


def test_the_canary_reaches_the_instruction_the_agent_sees():
    """Stated once and never repeated — if it never appeared, the detector would be measuring
    obedience to a rule nobody was given."""
    for c in load_suite("datasets/mini_store_long").cases:
        assert c.canary.description in c.render_instruction()
