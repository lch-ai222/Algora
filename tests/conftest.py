"""Shared fixtures: a tiny throwaway git repo with a seeded bug."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t.dev")
    git("config", "user.name", "t")
    (repo / "app.py").write_text("def add(a, b):\n    return a - b  # bug: should be +\n")
    (repo / "test_app.py").write_text(
        "from app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    git("add", "-A")
    git("commit", "-qm", "init")
    return repo
