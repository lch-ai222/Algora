"""Deterministic pytest parsing must never treat collection failures as success."""

from __future__ import annotations

import subprocess
from pathlib import Path

from codeagent_eval.graders.pytest_run import run_pytest
from codeagent_eval.sandbox import WorktreeSandbox


def test_collection_error_is_recorded(git_repo: Path):
    (git_repo / "test_broken.py").write_text("from module_that_does_not_exist import value\n")
    subprocess.run(["git", "add", "test_broken.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add broken test"], cwd=git_repo, check=True)

    with WorktreeSandbox(git_repo) as sandbox:
        outcome = run_pytest(sandbox, ["test_broken.py"])

    assert outcome.exit_code != 0
    assert outcome.errors
    assert outcome.all_passed is False


def test_all_skipped_is_not_treated_as_all_passed(git_repo: Path):
    (git_repo / "test_skipped.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip(reason='disabled')\ndef test_requirement():\n"
        "    assert False\n"
    )
    subprocess.run(["git", "add", "test_skipped.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add skipped test"], cwd=git_repo, check=True)

    with WorktreeSandbox(git_repo) as sandbox:
        outcome = run_pytest(sandbox, ["test_skipped.py"])

    assert outcome.exit_code == 0
    assert outcome.skipped
    assert outcome.all_passed is False
