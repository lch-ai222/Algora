"""Internal SWE-style benchmark: case schema, per-case materialization, hidden-test injection."""

from codeagent_eval.benchmark.case import CaseConstraints, EvalCase, Suite, case_dir, load_suite
from codeagent_eval.benchmark.materialize import (
    apply_reference_fix,
    defect_files,
    inject_hidden_tests,
    materialize_case,
)

__all__ = [
    "CaseConstraints",
    "EvalCase",
    "Suite",
    "load_suite",
    "case_dir",
    "materialize_case",
    "inject_hidden_tests",
    "apply_reference_fix",
    "defect_files",
]
