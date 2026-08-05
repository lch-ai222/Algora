"""Internal SWE-style benchmark: case schema, per-case materialization, hidden-test injection."""

from codeagent_eval.benchmark.case import (
    CanarySpec,
    CaseConstraints,
    EvalCase,
    FeedbackRound,
    MultiTurnSpec,
    Suite,
    case_dir,
    load_suite,
)
from codeagent_eval.benchmark.fingerprint import suite_fingerprint
from codeagent_eval.benchmark.materialize import (
    apply_reference_fix,
    defect_files,
    inject_hidden_tests,
    materialize_case,
)
from codeagent_eval.benchmark.multi_turn import (
    FeedbackDriver,
    FeedbackTurn,
    inject_all_feedback_tests,
    inject_feedback_round,
)

__all__ = [
    "suite_fingerprint",
    "CaseConstraints",
    "CanarySpec",
    "EvalCase",
    "FeedbackRound",
    "FeedbackDriver",
    "FeedbackTurn",
    "MultiTurnSpec",
    "Suite",
    "load_suite",
    "case_dir",
    "materialize_case",
    "inject_hidden_tests",
    "inject_feedback_round",
    "inject_all_feedback_tests",
    "apply_reference_fix",
    "defect_files",
]
