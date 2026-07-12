"""Version Compare classifies cases into improved / regressed / stable and sums deltas."""

from __future__ import annotations

from codeagent_eval.compare import compare_experiments


def _summary(exp_id, task, strict, cases):
    return {
        "experiment_id": exp_id,
        "suite": "mini_store",
        "suite_task_success": task,
        "suite_strict_success": strict,
        "cases": cases,
    }


def _case(cid, task, strict, tools=5.0, tokens=100.0):
    return {
        "case_id": cid,
        "task_success_rate": task,
        "strict_success_rate": strict,
        "tool_calls_mean": tools,
        "tokens_mean": tokens,
    }


def test_compare_buckets_and_deltas():
    v1 = _summary("v1", 0.5, 0.33, [
        _case("a", 1.0, 1.0), _case("b", 0.0, 0.0), _case("c", 0.5, 0.0),
    ])
    v2 = _summary("v2", 0.83, 0.78, [
        _case("a", 1.0, 1.0, tools=4.0), _case("b", 1.0, 1.0), _case("c", 1.0, 0.33),
    ])
    cmp = compare_experiments(v1, v2)
    assert set(cmp["improved"]) == {"b", "c"}  # keyed on Task Success rate
    assert cmp["regressed"] == []
    assert cmp["stable"] == ["a"]
    assert cmp["suite_task_delta"] == 0.33
    # per-case tool delta surfaced
    a_row = next(r for r in cmp["cases"] if r["case_id"] == "a")
    assert a_row["tool_calls_delta"] == -1.0


def test_compare_flags_regression():
    v1 = _summary("v1", 1.0, 1.0, [_case("a", 1.0, 1.0)])
    v2 = _summary("v2", 0.0, 0.0, [_case("a", 0.0, 0.0)])
    cmp = compare_experiments(v1, v2)
    assert cmp["regressed"] == ["a"]
    assert cmp["suite_task_delta"] == -1.0
