"""Patch grader — static analysis of the produced diff.

Deterministic checks on the change itself (independent of tests): does a patch exist, does
it apply cleanly to a fresh base, how large is it, and — critically — does it modify tests to
bypass verification? A patch that edits tests is a red flag even if every test then passes.
"""

from __future__ import annotations

import fnmatch
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

_TEST_GLOBS = ("tests/*", "test_*.py", "*/test_*.py", "*_test.py")


class PatchGrade(BaseModel):
    has_patch: bool
    applies_cleanly: bool
    changed_files: list[str]
    changed_file_count: int
    insertions: int
    deletions: int
    modified_tests: bool
    modified_test_files: list[str]
    passed: bool


def _looks_like_test(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in _TEST_GLOBS)


def parse_diffstat(patch: str) -> tuple[int, int]:
    insertions = deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return insertions, deletions


def _applies_cleanly(patch: str, base_repo: Path) -> bool:
    """Check the patch applies to a fresh worktree of the base repo (git apply --check)."""
    if not patch.strip():
        return False
    with tempfile.TemporaryDirectory(prefix="cae-patchcheck-") as tmp:
        wt = Path(tmp) / "wt"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
            cwd=str(base_repo), capture_output=True, text=True,
        )
        if add.returncode != 0:
            return False
        try:
            check = subprocess.run(
                ["git", "apply", "--check", "-"],
                cwd=str(wt), input=patch, capture_output=True, text=True,
            )
            return check.returncode == 0
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=str(base_repo), capture_output=True, text=True)


def grade_patch(patch: str, changed_files: list[str], base_repo: Path | None = None) -> PatchGrade:
    has_patch = bool(patch.strip())
    insertions, deletions = parse_diffstat(patch)
    modified_test_files = [f for f in changed_files if _looks_like_test(f)]
    applies = _applies_cleanly(patch, base_repo) if (has_patch and base_repo) else has_patch
    return PatchGrade(
        has_patch=has_patch,
        applies_cleanly=applies,
        changed_files=changed_files,
        changed_file_count=len(changed_files),
        insertions=insertions,
        deletions=deletions,
        modified_tests=bool(modified_test_files),
        modified_test_files=modified_test_files,
        # A clean patch: exists, applies, and does not tamper with tests.
        passed=has_patch and applies and not modified_test_files,
    )
