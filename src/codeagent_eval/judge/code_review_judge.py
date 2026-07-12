"""LLM-as-Judge for code-review quality — the one place a model grades, where no program
oracle exists (§7). Disciplined to be trustworthy:

- **Deterministic**: temperature=0.
- **Structured output**: a rubric of binary items, each with a verdict.
- **Forced citations**: every verdict must quote an exact snippet from the code; a citation that
  isn't found in the code drops confidence (the judge can't invent evidence).
- **Swap-averaging**: the rubric is judged twice (given order + reversed) to blunt position bias;
  per-item disagreement is surfaced, not hidden.

Never used to decide anything a program can check (tests pass / files changed / timeouts).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from codeagent_eval.llm import LlmProvider

JUDGE_PROMPT_VERSION = "code_review_judge_v1"


class RubricItem(BaseModel):
    id: str
    description: str  # a binary claim the reviewed code should satisfy


class ItemVerdict(BaseModel):
    item_id: str
    passed: bool
    citation: str = ""  # exact snippet from the code supporting the verdict
    citation_valid: bool = True
    reason: str = ""


class _LlmItemVerdict(BaseModel):
    item_id: str
    passed: bool
    citation: str = ""
    reason: str = ""


class _LlmJudgeResponse(BaseModel):
    verdicts: list[_LlmItemVerdict] = Field(default_factory=list)
    confidence: float = 0.5
    overall_reason: str = ""


class JudgeResult(BaseModel):
    score: int  # number of rubric items judged satisfied
    max_score: int
    passed_items: list[str]
    missed_items: list[str]
    confidence: float
    reason: str
    verdicts: list[ItemVerdict]
    disagreements: list[str] = Field(default_factory=list)  # items where swap runs disagreed


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _citation_in_code(citation: str, code: str) -> bool:
    if not citation.strip():
        return False
    return _normalize(citation) in _normalize(code)


def _build_prompt(code: str, rubric: list[RubricItem]) -> tuple[str, str]:
    system = (
        "You are a strict code reviewer acting as an evaluation judge. For each rubric item, "
        "decide whether the code SATISFIES it (passed=true) or not (passed=false). You MUST quote "
        "an exact snippet from the code as `citation` supporting each verdict — do not paraphrase, "
        "copy characters verbatim. If you cannot cite evidence, set passed=false. Output JSON only."
    )
    items = "\n".join(f"- {it.id}: {it.description}" for it in rubric)
    user = (
        f"CODE UNDER REVIEW:\n```\n{code}\n```\n\n"
        f"RUBRIC ITEMS:\n{items}\n\n"
        'Return JSON: {"verdicts":[{"item_id","passed","citation","reason"}],'
        '"confidence":0..1,"overall_reason"}'
    )
    return system, user


def _judge_once(
    provider: LlmProvider, code: str, rubric: list[RubricItem], temperature: float
) -> dict[str, _LlmItemVerdict]:
    system, user = _build_prompt(code, rubric)
    resp = provider.json_completion(
        system_prompt=system,
        user_prompt=user,
        response_model=_LlmJudgeResponse,
        temperature=temperature,
        call_site="judge.code_review",
        prompt_version=JUDGE_PROMPT_VERSION,
    )
    if resp is None:
        return {}
    return {v.item_id: v for v in resp.verdicts}


def judge_code_review(
    provider: LlmProvider,
    code: str,
    rubric: list[RubricItem],
    *,
    temperature: float = 0.0,
    swap: bool = True,
) -> JudgeResult | None:
    """Judge ``code`` against ``rubric``. Returns None if the provider is unavailable."""
    forward = _judge_once(provider, code, rubric, temperature)
    if not forward:
        return None
    runs = [forward]
    if swap:
        reversed_rubric = list(reversed(rubric))
        backward = _judge_once(provider, code, reversed_rubric, temperature)
        if backward:
            runs.append(backward)

    verdicts: list[ItemVerdict] = []
    disagreements: list[str] = []
    for item in rubric:
        votes = [r[item.id].passed for r in runs if item.id in r]
        cites = [r[item.id].citation for r in runs if item.id in r]
        reasons = [r[item.id].reason for r in runs if item.id in r]
        if not votes:
            verdicts.append(ItemVerdict(item_id=item.id, passed=False, citation_valid=False,
                                        reason="judge did not return a verdict for this item"))
            continue
        if len(set(votes)) > 1:
            disagreements.append(item.id)
        # Swap-averaged verdict: pass only if the (majority of) runs agree it passed.
        passed = sum(votes) > len(votes) / 2
        citation = next((c for c in cites if c.strip()), "")
        valid = _citation_in_code(citation, code)
        verdicts.append(ItemVerdict(
            item_id=item.id, passed=passed, citation=citation, citation_valid=valid,
            reason=reasons[0] if reasons else "",
        ))

    passed_items = [v.item_id for v in verdicts if v.passed]
    missed_items = [v.item_id for v in verdicts if not v.passed]
    # Confidence: penalize uncited verdicts and swap disagreements.
    invalid_cites = sum(1 for v in verdicts if v.passed and not v.citation_valid)
    n = max(1, len(rubric))
    confidence = round(max(0.0, 1.0 - (invalid_cites + len(disagreements)) / n), 3)
    return JudgeResult(
        score=len(passed_items),
        max_score=len(rubric),
        passed_items=passed_items,
        missed_items=missed_items,
        confidence=confidence,
        reason=f"{len(passed_items)}/{len(rubric)} rubric items satisfied; "
               f"{len(disagreements)} swap disagreement(s), {invalid_cites} uncited pass(es)",
        verdicts=verdicts,
        disagreements=disagreements,
    )
