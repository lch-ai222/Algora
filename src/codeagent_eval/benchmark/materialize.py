"""Materialize a per-case git repo: clean source + exactly this case's defect, committed once.

This is the key to clean isolation and no-leak: the base commit contains only the case's
defect (every other module is correct), and the *fix is never in git history*, so an agent
cannot retrieve the solution with `git checkout`. Hidden tests are injected separately, only
at grade time, so the agent can never read or overfit to them.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from codeagent_eval.benchmark.case import EvalCase

_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache")

#: Every real Python repo carries something like this, and without it the case repo has no way
#: to say what is source and what is build residue. Running pytest writes bytecode under
#: tests/, which git then reports as a change — so an agent that actually runs the tests gets
#: charged with editing test files and blowing the changed-file limit. The MiniAgent never hit
#: it only because its sandbox sets PYTHONDONTWRITEBYTECODE; an external agent runs in its own
#: environment, so the fix has to live in the repository rather than in one runner's env.
_DEFAULT_GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
*.egg-info/
build/
dist/
.coverage
"""


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def materialize_case(
    suite_dir: str | Path, clean_repo: str | Path, case: EvalCase, build_root: str | Path | None = None
) -> Path:
    """Build a fresh git repo for ``case`` and return its path. Caller owns cleanup."""
    suite_dir = Path(suite_dir)
    clean_repo = Path(clean_repo)
    parent = Path(build_root) if build_root else Path(tempfile.mkdtemp(prefix="cae-build-"))
    parent.mkdir(parents=True, exist_ok=True)
    repo = parent / case.case_id
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(clean_repo, repo, ignore=_IGNORE)

    # Overlay the case defect (buggy/stub variants of one or more source files).
    defect_dir = suite_dir / "cases" / case.case_id / "defect"
    if defect_dir.is_dir():
        for src in defect_dir.rglob("*"):
            if src.is_file():
                dest = repo / src.relative_to(defect_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    gitignore = repo / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_DEFAULT_GITIGNORE)

    _git(["init", "-q"], repo)
    _git(["config", "user.email", "bench@codeagent.eval"], repo)
    _git(["config", "user.name", "codeagent-eval"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", f"base: {case.case_id} (defect present)"], repo)
    return repo


def defect_files(suite_dir: str | Path, case: EvalCase) -> list[str]:
    """Repo-relative paths this case's defect overlays (i.e. the files a fix should touch)."""
    defect_dir = Path(suite_dir) / "cases" / case.case_id / "defect"
    if not defect_dir.is_dir():
        return []
    return sorted(str(p.relative_to(defect_dir)) for p in defect_dir.rglob("*") if p.is_file())


def apply_reference_fix(
    workspace_root: str | Path, suite_dir: str | Path, clean_repo: str | Path, case: EvalCase
) -> list[str]:
    """Restore the clean (correct) version of every defect file into the workspace.

    This is the known-good reference solution — used by selfcheck to prove a case is solvable
    and by the reference-agent tier in the discrimination check (M4). Returns files restored.
    """
    workspace_root, clean_repo = Path(workspace_root), Path(clean_repo)
    restored: list[str] = []
    for rel in defect_files(suite_dir, case):
        src = clean_repo / rel
        dest = workspace_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        restored.append(rel)
    return restored


def inject_hidden_tests(workspace_root: str | Path, suite_dir: str | Path, case: EvalCase) -> list[str]:
    """Copy the case's hidden test files into the workspace's tests/ dir (grade time only).

    Returns the workspace-relative paths written, for cleanup/trace. Called after the agent
    has finished so the hidden tests are never visible during the trial.
    """
    workspace_root = Path(workspace_root)
    hidden_dir = Path(suite_dir) / "cases" / case.case_id / "hidden"
    written: list[str] = []
    if not hidden_dir.is_dir():
        return written
    dest_dir = workspace_root / "tests"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(hidden_dir.glob("*.py")):
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        written.append(str(dest.relative_to(workspace_root)))
    return written
