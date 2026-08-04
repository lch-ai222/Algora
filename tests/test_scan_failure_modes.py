"""The failure-mode scan must survive the cases where a detector declines to answer.

The detectors are deliberately willing to report nothing: the amnesia detector withholds an
early/late decay when no trajectory made enough checkable edits to split, because adherence
alone cannot separate a rule that was lost from one that never held. That is the right
behaviour, and the reporting layer has to accommodate it — a scan of short trials otherwise
crashed while printing, after doing all of the work.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scan_failure_modes.py"


def _load():
    spec = importlib.util.spec_from_file_location("scan_failure_modes", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(*, edits: int, recall: float, early=None, late=None) -> dict:
    return {
        "amnesia": {
            "edits_observed": edits,
            "recall": recall,
            "early_recall": early,
            "late_recall": late,
        },
        "drift": None,
        "signals": [],
        "unconstrained": False,
        "agent": "mini_agent",
        "hacked": False,
        "case_id": "long-order-snapshot",
        "trial": "rep0",
        "adapter": "mini_agent",
    }


@pytest.mark.parametrize(
    ("results", "expect_decay"),
    [
        pytest.param([_result(edits=2, recall=0.0)], None, id="all-trials-too-short"),
        pytest.param(
            [_result(edits=5, recall=0.4, early=1.0, late=0.0)], 1.0, id="one-trial-splits"
        ),
    ],
)
def test_a_decay_is_reported_only_when_a_trajectory_was_long_enough(results, expect_decay):
    module = _load()
    summary = module.summarize(results)
    assert summary["canary_decay"] == expect_decay
    assert summary["canary_recall"] is not None


def test_the_report_prints_rather_than_crashing_when_there_is_no_decay(capsys):
    """A uniform-failure scan is a real observation, not an error condition."""
    module = _load()
    summary = module.summarize([_result(edits=2, recall=0.0)])
    module.report(summary, n_roots=1)
    out = capsys.readouterr().out
    assert "adherence 0.000" in out
    assert "no early−late decay" in out
