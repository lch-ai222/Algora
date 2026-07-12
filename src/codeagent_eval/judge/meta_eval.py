"""Judge meta-eval — "evaluating the evaluator" (ported from ft_diag_agent).

An LLM judge is only trustworthy as a hard gate if it agrees with humans. This scores each
judge dimension against a small human-labelled gold set (per-dimension agreement + Cohen's
kappa) and derives a *trust map*: dimensions below threshold are auto-downgraded from hard
gate to advisory. The metric math is pure and unit-testable; producing predictions needs the
judge (or, offline, a deterministic stub).

The domain glue differs from ft_diag (code review vs fault trees) but the math is identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

RUBRIC_VERSION = "judge_meta_eval_v1"
GOLD_VERSION = "judge_gold_v1"

# "Substantial agreement" (Landis & Koch) is the trust bar for a hard gate.
DEFAULT_MIN_KAPPA = 0.6
DEFAULT_MIN_AGREEMENT = 0.8


# --- pure metrics ----------------------------------------------------------- #
def agreement_rate(gold: list[bool], pred: list[bool]) -> float | None:
    if not gold:
        return None
    return sum(1 for g, p in zip(gold, pred, strict=False) if g == p) / len(gold)


def cohen_kappa(gold: list[bool], pred: list[bool]) -> float | None:
    """Cohen's kappa for two binary raters.

    When both raters are constant (chance agreement p_e == 1) kappa is undefined; by
    convention we return 1.0 on perfect observed agreement and 0.0 otherwise, which is what
    trust gating expects.
    """
    n = len(gold)
    if n == 0:
        return None
    p_o = sum(1 for g, p in zip(gold, pred, strict=False) if g == p) / n
    p_gold_true = sum(1 for g in gold if g) / n
    p_pred_true = sum(1 for p in pred if p) / n
    p_e = p_gold_true * p_pred_true + (1 - p_gold_true) * (1 - p_pred_true)
    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0
    return (p_o - p_e) / (1 - p_e)


class DimensionMetaEval(BaseModel):
    dimension: str
    sample_count: int
    agreement_rate: float | None
    cohen_kappa: float | None
    min_kappa: float
    min_agreement: float
    trusted: bool
    downgrade_reason: str | None = None


class MetaEvalReport(BaseModel):
    rubric_version: str = RUBRIC_VERSION
    gold_version: str = GOLD_VERSION
    llm_used: bool = False
    dimensions: list[DimensionMetaEval] = Field(default_factory=list)

    def trust_map(self) -> dict[str, bool]:
        """Only dimensions measured below threshold appear as False (downgraded to advisory)."""
        return {d.dimension: d.trusted for d in self.dimensions}


def evaluate_dimension(
    dimension: str,
    pairs: list[tuple[bool, bool]],
    *,
    min_kappa: float = DEFAULT_MIN_KAPPA,
    min_agreement: float = DEFAULT_MIN_AGREEMENT,
) -> DimensionMetaEval:
    gold = [g for g, _ in pairs]
    pred = [p for _, p in pairs]
    agreement = agreement_rate(gold, pred)
    kappa = cohen_kappa(gold, pred)
    if not pairs:
        # Unmeasured -> left trusted; trust is only revoked on measured underperformance.
        trusted, reason = True, None
    else:
        trusted = (agreement is not None and agreement >= min_agreement) and (
            kappa is not None and kappa >= min_kappa
        )
        reason = None if trusted else (
            f"agreement={_fmt(agreement)}<{min_agreement} or kappa={_fmt(kappa)}<{min_kappa}"
        )
    return DimensionMetaEval(
        dimension=dimension,
        sample_count=len(pairs),
        agreement_rate=agreement,
        cohen_kappa=kappa,
        min_kappa=min_kappa,
        min_agreement=min_agreement,
        trusted=trusted,
        downgrade_reason=reason,
    )


def build_meta_eval_report(
    pairs_by_dimension: dict[str, list[tuple[bool, bool]]],
    *,
    llm_used: bool = False,
    min_kappa: float = DEFAULT_MIN_KAPPA,
    min_agreement: float = DEFAULT_MIN_AGREEMENT,
) -> MetaEvalReport:
    dimensions = [
        evaluate_dimension(dim, pairs, min_kappa=min_kappa, min_agreement=min_agreement)
        for dim, pairs in pairs_by_dimension.items()
    ]
    return MetaEvalReport(llm_used=llm_used, dimensions=dimensions)


def save_meta_eval_report(report: MetaEvalReport, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return target


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)
