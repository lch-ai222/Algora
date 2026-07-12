"""Human-labelled gold set for judge meta-eval + the runner that scores the judge against it.

Each gold case is a snippet of code plus rubric items, where a human has recorded the correct
verdict (gold_passed) for each item. Running the judge and comparing per-dimension yields the
agreement/kappa that decides whether each judge dimension is trusted as a hard gate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from codeagent_eval.judge.code_review_judge import RubricItem, judge_code_review
from codeagent_eval.judge.meta_eval import (
    DEFAULT_MIN_AGREEMENT,
    DEFAULT_MIN_KAPPA,
    MetaEvalReport,
    build_meta_eval_report,
)
from codeagent_eval.llm import LlmProvider

# A judge function: given code + rubric, return {item_id: judged_passed}.
JudgeFn = Callable[[str, list[RubricItem]], dict[str, bool]]


class GoldItem(BaseModel):
    id: str
    dimension: str  # groups items so kappa is computed per judge dimension
    description: str
    gold_passed: bool  # the correct verdict a trustworthy judge should produce


class GoldCase(BaseModel):
    case_id: str
    code: str
    items: list[GoldItem]


def load_gold(path: str | Path) -> list[GoldCase]:
    lines = Path(path).read_text().splitlines()
    return [GoldCase.model_validate_json(ln) for ln in lines if ln.strip()]


def provider_judge_fn(provider: LlmProvider) -> JudgeFn:
    def fn(code: str, rubric: list[RubricItem]) -> dict[str, bool]:
        result = judge_code_review(provider, code, rubric)
        return {v.item_id: v.passed for v in result.verdicts} if result else {}

    return fn


def run_meta_eval(
    gold_cases: list[GoldCase],
    judge_fn: JudgeFn,
    *,
    llm_used: bool = False,
    min_kappa: float = DEFAULT_MIN_KAPPA,
    min_agreement: float = DEFAULT_MIN_AGREEMENT,
) -> MetaEvalReport:
    pairs_by_dimension: dict[str, list[tuple[bool, bool]]] = {}
    for case in gold_cases:
        rubric = [RubricItem(id=it.id, description=it.description) for it in case.items]
        preds = judge_fn(case.code, rubric)
        for it in case.items:
            if it.id in preds:  # skip items the judge didn't return
                pairs_by_dimension.setdefault(it.dimension, []).append((it.gold_passed, preds[it.id]))
    return build_meta_eval_report(
        pairs_by_dimension, llm_used=llm_used, min_kappa=min_kappa, min_agreement=min_agreement
    )
