"""Process-isolation sandbox built on a throwaway git worktree.

Each trial gets an isolated checkout of the target repo at a fixed base commit, run in a
temp directory. Commands go through ``CommandPolicy`` (deny-by-default), a wall-clock
timeout, output truncation, and a scrubbed environment. On exit the patch (diff vs base)
and logs are exportable, then the worktree is removed. This is the MVP isolation layer;
Docker is the documented upgrade for kernel-level / network isolation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel

from codeagent_eval.sandbox.policy import CommandPolicy

# Cap captured output so a runaway command can't blow up memory or the trace.
DEFAULT_MAX_OUTPUT_CHARS = 20_000


class CommandResult(BaseModel):
    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    timed_out: bool = False
    blocked: bool = False
    block_reason: str | None = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.blocked and not self.timed_out


class SandboxError(RuntimeError):
    pass


def _scrubbed_env(home: Path) -> dict[str, str]:
    """Minimal environment: keep PATH so python/git resolve, drop proxies and secrets,
    point HOME at the sandbox so nothing touches the real user config."""
    keep = {"PATH", "LANG", "LC_ALL", "TZ", "TMPDIR"}
    env = {k: v for k, v in os.environ.items() if k in keep}
    # Ensure the interpreter running the sandbox is resolvable as `python`/`python3` inside
    # the worktree even when the venv isn't on the inherited PATH (unactivated venv, CI).
    interpreter_dir = os.path.dirname(sys.executable)
    env["PATH"] = os.pathsep.join(filter(None, [interpreter_dir, env.get("PATH", "")]))
    env.update(
        {
            "HOME": str(home),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            # Neutralize any proxy inherited from the parent (belt-and-suspenders vs network).
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
        }
    )
    return env


class WorktreeSandbox:
    """Isolated git worktree for one trial. Use as a context manager."""

    def __init__(
        self,
        repo_path: str | Path,
        base_commit: str = "HEAD",
        *,
        policy: CommandPolicy | None = None,
        work_root: str | Path | None = None,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.base_commit = base_commit
        self.policy = policy or CommandPolicy()
        self.work_root = Path(work_root) if work_root else None
        self.max_output_chars = max_output_chars
        self.worktree_path: Path | None = None
        self._resolved_base: str | None = None
        self._tmp_created: Path | None = None

    # -- lifecycle ---------------------------------------------------------- #
    def __enter__(self) -> WorktreeSandbox:
        self.setup()
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    def setup(self) -> Path:
        if not (self.repo_path / ".git").exists():
            raise SandboxError(f"{self.repo_path} is not a git repository")
        # Resolve the base commit to a stable sha so later diffs are unambiguous.
        self._resolved_base = self._git(["rev-parse", self.base_commit], cwd=self.repo_path).strip()
        parent = self.work_root or Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        self._tmp_created = Path(tempfile.mkdtemp(prefix="cae-wt-", dir=str(parent)))
        self.worktree_path = self._tmp_created / "workspace"
        self._git(
            ["worktree", "add", "--detach", str(self.worktree_path), self._resolved_base],
            cwd=self.repo_path,
        )
        return self.worktree_path

    def cleanup(self) -> None:
        if self.worktree_path and self.worktree_path.exists():
            # --force because the trial will have left uncommitted edits.
            try:
                self._git(["worktree", "remove", "--force", str(self.worktree_path)], cwd=self.repo_path)
            except SandboxError:
                pass
            self._git(["worktree", "prune"], cwd=self.repo_path, check=False)
        if self._tmp_created and self._tmp_created.exists():
            shutil.rmtree(self._tmp_created, ignore_errors=True)
        self.worktree_path = None
        self._tmp_created = None

    # -- workspace paths ---------------------------------------------------- #
    @property
    def root(self) -> Path:
        if self.worktree_path is None:
            raise SandboxError("sandbox not set up; call setup() or use as a context manager")
        return self.worktree_path

    def resolve(self, rel_path: str) -> Path:
        """Resolve a workspace-relative path, refusing anything that escapes the worktree."""
        candidate = (self.root / rel_path).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise SandboxError(f"path escapes workspace: {rel_path!r}")
        return candidate

    # -- command execution -------------------------------------------------- #
    def run(self, command: str, timeout: int = 120) -> CommandResult:
        decision = self.policy.check(command)
        if not decision.allowed:
            return CommandResult(command=command, blocked=True, block_reason=decision.reason)

        started = perf_counter()
        try:
            proc = subprocess.run(
                decision.argv,
                cwd=str(self.root),
                env=_scrubbed_env(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                timed_out=True,
                stdout=_truncate(exc.stdout, self.max_output_chars)[0],
                stderr=_truncate(exc.stderr, self.max_output_chars)[0],
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except FileNotFoundError:
            return CommandResult(
                command=command, blocked=True, block_reason=f"executable not found: {decision.argv[0]!r}"
            )
        stdout, t1 = _truncate(proc.stdout, self.max_output_chars)
        stderr, t2 = _truncate(proc.stderr, self.max_output_chars)
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated=t1 or t2,
            duration_ms=int((perf_counter() - started) * 1000),
        )

    # -- artifacts ---------------------------------------------------------- #
    def export_patch(self) -> str:
        """Unified diff of the current worktree state vs the base commit."""
        # Stage nothing permanently: diff working tree (including untracked via intent-to-add).
        self._git(["add", "-AN"], cwd=self.root, check=False)
        return self._git(["diff", self._resolved_base or self.base_commit], cwd=self.root, check=False)

    def changed_files(self) -> list[str]:
        out = self._git(
            ["diff", "--name-only", self._resolved_base or self.base_commit], cwd=self.root, check=False
        )
        return [line for line in out.splitlines() if line.strip()]

    # -- internal ----------------------------------------------------------- #
    def _git(self, args: list[str], cwd: Path, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise SandboxError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout


def _truncate(text: str | None, limit: int) -> tuple[str, bool]:
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n…[{len(text) - limit} chars truncated]…\n{text[-tail:]}", True
