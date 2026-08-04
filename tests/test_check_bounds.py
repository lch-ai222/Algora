"""W1-5: the deterministic-bounds gate must catch benchmark rot, not just report it.

``check_bounds`` is a CI gate, so its own failure modes matter: a gate that passes when the
suite has drifted is worse than no gate, because every agent number measured afterwards looks
trustworthy. These tests drive it with synthetic summaries instead of real experiments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_bounds


def _summary(tier: str, *, cases: dict[str, float | None], infra: int = 0) -> dict:
    rates = [r for r in cases.values() if r is not None]
    return {
        "experiment_id": f"{tier}-test",
        "suite_task_success": (sum(rates) / len(rates)) if rates else None,
        "infra_failures": infra,
        "cases": [{"case_id": cid, "task_success_rate": r} for cid, r in cases.items()],
    }


@pytest.fixture
def fake_experiments(monkeypatch):
    """Replace run_experiment with a scripted per-tier summary."""

    def install(summaries: dict[str, dict]):
        def fake_run(kind, suite_dir, provider, repeats, case_filter, out_root, *a, **kw):  # noqa: ARG001
            return summaries[kind]

        monkeypatch.setattr(check_bounds, "run_experiment", fake_run)

    return install


def test_healthy_suite_passes(fake_experiments, tmp_path):
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": 1.0, "b": 1.0}),
            "none": _summary("none", cases={"a": 0.0, "b": 0.0}),
        }
    )
    assert check_bounds.check_suite(Path("datasets/fake"), tmp_path) == []


def test_unsolvable_case_fails_the_reference_ceiling(fake_experiments, tmp_path):
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": 1.0, "b": 0.0}),
            "none": _summary("none", cases={"a": 0.0, "b": 0.0}),
        }
    )
    failures = check_bounds.check_suite(Path("datasets/fake"), tmp_path)

    assert any("reference/b" in f for f in failures)


def test_case_passing_without_work_fails_the_none_floor(fake_experiments, tmp_path):
    """A none-tier pass means the case is scored solved with an empty patch."""
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": 1.0, "b": 1.0}),
            "none": _summary("none", cases={"a": 0.0, "b": 1.0}),
        }
    )
    failures = check_bounds.check_suite(Path("datasets/fake"), tmp_path)

    assert any("none/b" in f for f in failures)


def test_per_case_check_catches_rot_hidden_by_a_correct_average(fake_experiments, tmp_path):
    """Two cases drifting in opposite directions leave the suite mean at 1.00 while both are
    broken — the reason this gate does not stop at the aggregate."""
    summary = _summary("reference", cases={"a": 1.2, "b": 0.8})
    assert summary["suite_task_success"] == pytest.approx(1.0)
    fake_experiments(
        {"reference": summary, "none": _summary("none", cases={"a": 0.0, "b": 0.0})}
    )
    failures = check_bounds.check_suite(Path("datasets/fake"), tmp_path)

    assert any("reference/a" in f for f in failures)
    assert any("reference/b" in f for f in failures)


def test_infra_failures_are_reported_separately_from_scores(fake_experiments, tmp_path):
    """A harness failure makes the score no evidence either way, so it cannot pass silently
    even when the surviving trials happen to hit the expected bound."""
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": 1.0}, infra=2),
            "none": _summary("none", cases={"a": 0.0}),
        }
    )
    failures = check_bounds.check_suite(Path("datasets/fake"), tmp_path)

    assert any("infra failures" in f for f in failures)


def test_missing_rate_is_a_failure_not_a_skip(fake_experiments, tmp_path):
    """`task_success_rate=None` means every trial was infra-invalid; treating it as pass would
    turn a totally broken suite into a green build."""
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": None}, infra=1),
            "none": _summary("none", cases={"a": 0.0}),
        }
    )
    failures = check_bounds.check_suite(Path("datasets/fake"), tmp_path)

    assert any("expected 1.0" in f for f in failures)


def test_cli_returns_nonzero_when_bounds_break(fake_experiments, tmp_path, capsys):
    fake_experiments(
        {
            "reference": _summary("reference", cases={"a": 0.5}),
            "none": _summary("none", cases={"a": 0.0}),
        }
    )
    code = check_bounds.main(["--suite", "datasets/fake", "--out", str(tmp_path)])

    assert code == 1
    assert "deterministic bounds violated" in capsys.readouterr().err
