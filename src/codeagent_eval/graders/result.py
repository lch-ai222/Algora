"""Combine the deterministic graders into Task Success vs Strict Success.

- Task Success = functional correctness: target + regression + hidden tests all pass.
- Strict Success = Task Success AND engineering-compliant: constraints hold AND the patch is
  clean (exists, applies, does not modify tests). This is the OctoCodingBench-style split that
  surfaces "functionally done but engineering non-compliant".
"""

from __future__ import annotations

from pydantic import BaseModel

from codeagent_eval.graders.constraint_grader import ConstraintGrade
from codeagent_eval.graders.patch_grader import PatchGrade
from codeagent_eval.graders.test_grader import TestGrade


class GradeResult(BaseModel):
    case_id: str
    test: TestGrade
    constraint: ConstraintGrade
    patch: PatchGrade
    task_success: bool
    strict_success: bool

    def summary_row(self) -> dict:
        """Flat dict for CSV/table output."""
        return {
            "case_id": self.case_id,
            "task_success": self.task_success,
            "strict_success": self.strict_success,
            "target_passed": self.test.target_passed,
            "hidden_pass_rate": self.test.hidden_pass_rate,
            "regression_passed": self.test.regression_passed,
            "changed_files": self.patch.changed_file_count,
            "modified_tests": self.patch.modified_tests,
            "constraint_violations": len(self.constraint.violations),
        }


def combine(case_id: str, test: TestGrade, constraint: ConstraintGrade, patch: PatchGrade) -> GradeResult:
    task_success = test.functional_success
    strict_success = task_success and constraint.passed and patch.passed
    return GradeResult(
        case_id=case_id,
        test=test,
        constraint=constraint,
        patch=patch,
        task_success=task_success,
        strict_success=strict_success,
    )
