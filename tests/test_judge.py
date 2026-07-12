"""M5: judge meta-eval math, the code-review judge (citations + swap), and HumanEval executor.
All offline via deterministic stubs / fake providers — no API key."""

from __future__ import annotations

from codeagent_eval.benchmark.humaneval_plus import (
    HumanEvalProblem,
    _Completion,
    evaluate_problem,
    run_program,
)
from codeagent_eval.judge.code_review_judge import (
    RubricItem,
    _LlmItemVerdict,
    _LlmJudgeResponse,
    judge_code_review,
)
from codeagent_eval.judge.gold import GoldCase, GoldItem, run_meta_eval
from codeagent_eval.judge.meta_eval import agreement_rate, build_meta_eval_report, cohen_kappa


# --------------------------------------------------------------------------- #
# meta-eval math
# --------------------------------------------------------------------------- #
def test_agreement_and_kappa_perfect():
    gold = [True, False, True, False]
    assert agreement_rate(gold, gold) == 1.0
    assert cohen_kappa(gold, gold) == 1.0


def test_kappa_constant_raters():
    # both always True -> chance agreement 1; convention returns 1.0 on perfect obs agreement
    assert cohen_kappa([True, True], [True, True]) == 1.0
    # gold all True, pred all False -> 0 observed agreement
    assert cohen_kappa([True, True], [False, False]) == 0.0


def test_kappa_partial_below_chance():
    gold = [True, True, False, False]
    pred = [True, False, True, False]  # 50% agreement, chance 50% -> kappa 0
    assert cohen_kappa(gold, pred) == 0.0


def test_trust_map_downgrades_low_kappa():
    # a dimension where judge disagrees a lot -> not trusted
    bad = [(True, False), (True, False), (False, True), (False, True)]
    good = [(True, True), (False, False), (True, True), (False, False)]
    report = build_meta_eval_report({"BAD": bad, "GOOD": good})
    tmap = report.trust_map()
    assert tmap["GOOD"] is True
    assert tmap["BAD"] is False


# --------------------------------------------------------------------------- #
# code-review judge (fake provider)
# --------------------------------------------------------------------------- #
class _FakeJudgeProvider:
    """json_completion returns a preset judge response (citations may be valid or not)."""

    def __init__(self, verdicts: list[_LlmItemVerdict]):
        self._resp = _LlmJudgeResponse(verdicts=verdicts, confidence=0.9, overall_reason="stub")
        self.last_error = None

    def json_completion(self, *, response_model, **kwargs):  # noqa: ARG002
        return self._resp


CODE = "def add(a, b):\n    return a + b\n"


def test_judge_scores_and_validates_citations():
    rubric = [RubricItem(id="i1", description="adds a and b"), RubricItem(id="i2", description="handles None")]
    provider = _FakeJudgeProvider([
        _LlmItemVerdict(item_id="i1", passed=True, citation="return a + b", reason="ok"),
        _LlmItemVerdict(item_id="i2", passed=False, citation="", reason="no None handling"),
    ])
    res = judge_code_review(provider, CODE, rubric)
    assert res is not None
    assert res.score == 1 and res.max_score == 2
    assert res.passed_items == ["i1"] and res.missed_items == ["i2"]
    v1 = next(v for v in res.verdicts if v.item_id == "i1")
    assert v1.citation_valid is True  # "return a + b" is in the code


def test_judge_penalizes_uncited_pass():
    rubric = [RubricItem(id="i1", description="adds a and b")]
    # claims passed but cites text NOT in the code -> confidence penalty
    provider = _FakeJudgeProvider([_LlmItemVerdict(item_id="i1", passed=True, citation="import os", reason="x")])
    res = judge_code_review(provider, CODE, rubric)
    assert res.verdicts[0].citation_valid is False
    assert res.confidence < 1.0


def test_meta_eval_run_with_stub_judge():
    gold = [GoldCase(case_id="c", code=CODE, items=[
        GoldItem(id="a", dimension="CORRECTNESS", description="adds", gold_passed=True),
        GoldItem(id="b", dimension="EDGE_CASES", description="None", gold_passed=False),
    ])]
    # a perfect judge that agrees with gold
    def judge_fn(code, rubric):  # noqa: ARG001
        return {"a": True, "b": False}

    report = run_meta_eval(gold, judge_fn)
    tmap = report.trust_map()
    assert tmap["CORRECTNESS"] is True and tmap["EDGE_CASES"] is True


# --------------------------------------------------------------------------- #
# HumanEval executor
# --------------------------------------------------------------------------- #
def test_run_program_pass_and_fail():
    ok, err, to = run_program("def f():\n    return 1\n", "assert f() == 1")
    assert ok and err is None and not to
    bad, err2, _ = run_program("def f():\n    return 2\n", "assert f() == 1")
    assert not bad and err2 is not None


class _FakeCompletionProvider:
    def __init__(self, code: str):
        self._code = code
        self.last_error = None

    def json_completion(self, *, response_model, **kwargs):  # noqa: ARG002
        return _Completion(code=self._code)


def test_evaluate_problem_correct_and_wrong():
    prob = HumanEvalProblem(
        task_id="t", prompt="def inc(x): ...", entry_point="inc",
        canonical_solution="def inc(x):\n    return x + 1\n",
        base_tests="assert inc(1) == 2", plus_tests="assert inc(-1) == 0",
    )
    good = evaluate_problem(_FakeCompletionProvider("def inc(x):\n    return x + 1\n"), prob)
    assert good.base_passed and good.plus_passed
    wrong = evaluate_problem(_FakeCompletionProvider("def inc(x):\n    return x + 2\n"), prob)
    assert not wrong.base_passed and not wrong.plus_passed
