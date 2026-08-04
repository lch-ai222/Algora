"""Shared fixtures: a tiny throwaway git repo with a seeded bug, and a fake ``claude`` CLI."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
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


@dataclass
class FakeClaude:
    """Handle to an executable ``claude`` stand-in plus its scenario/argv-dump files."""

    cli_path: Path
    scenario_path: Path
    dump_path: Path

    def script(self, **scenario) -> None:
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    def invocation(self) -> dict:
        """argv/env/cwd the adapter actually launched the CLI with."""
        return json.loads(self.dump_path.read_text(encoding="utf-8"))


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    driver = Path(__file__).parent / "fake_claude.py"
    cli = bin_dir / "claude"
    cli.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(driver))} \"$@\"\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)

    handle = FakeClaude(
        cli_path=cli,
        scenario_path=tmp_path / "scenario.json",
        dump_path=tmp_path / "invocation.json",
    )
    handle.script()
    # These reach the child only because they match the adapter's CLAUDE_ passthrough prefix,
    # which is exactly the mechanism the isolation test pins down.
    monkeypatch.setenv("CLAUDE_FAKE_SCRIPT", str(handle.scenario_path))
    monkeypatch.setenv("CLAUDE_FAKE_DUMP", str(handle.dump_path))
    return handle
