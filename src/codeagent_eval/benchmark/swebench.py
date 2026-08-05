"""SWE-bench adapter (interface + one runnable compatibility sample).

Reads the **official SWE-bench instance schema** (`instance_id / repo / base_commit /
problem_statement / patch / test_patch / FAIL_TO_PASS / PASS_TO_PASS / environment_setup_commit`)
and runs the same flow SWE-bench uses: check out the repo at base_commit, apply `test_patch`
(brings the tests), apply a candidate patch (gold or agent-produced), then require FAIL_TO_PASS
to flip to passing while PASS_TO_PASS stays passing → *resolved*.

Honesty (say this in the demo): running a *real* SWE-bench Lite instance needs cloning a large
GitHub repo at a historical commit and reproducing its per-repo environment (why the official
harness uses Docker). We ship one **compatibility sample** backed by a small self-contained repo
(`repo_local`) so the adapter runs end-to-end here; real instances plug into the same schema and
require the environment setup described in `docs/swebench_and_docker.md`. Results from the
compatibility sample are labelled "Compatibility Sample", never a leaderboard number.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from codeagent_eval.agent.loop import AgentConfig, MiniAgent
from codeagent_eval.graders.pytest_run import run_pytest
from codeagent_eval.models import AgentTask
from codeagent_eval.sandbox.worktree import WorktreeSandbox

_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache")


class SWEBenchInstance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    instance_id: str
    repo: str
    base_commit: str = "HEAD"
    problem_statement: str = ""
    patch: str = ""  # gold solution patch (unified diff)
    test_patch: str = ""  # adds/modifies the tests referenced below
    fail_to_pass: list[str] = Field(default_factory=list, alias="FAIL_TO_PASS")
    pass_to_pass: list[str] = Field(default_factory=list, alias="PASS_TO_PASS")
    environment_setup_commit: str | None = None
    #: The repository release an instance belongs to. The official harness keys its install
    #: recipes on this, and instances sharing a version can share one built environment.
    version: str = "unknown"
    # NON-official: path (relative to the suite dir) to a bundled base repo for compatibility
    # samples. Real instances leave this None and are fetched by repo@base_commit.
    repo_local: str | None = None

    @field_validator("fail_to_pass", "pass_to_pass", mode="before")
    @classmethod
    def _parse_maybe_json(cls, v):
        # The official dataset encodes these as a JSON string; accept both.
        if isinstance(v, str):
            return json.loads(v)
        return v


class InstanceResult(BaseModel):
    instance_id: str
    mode: str  # gold | agent
    resolved: bool
    fail_to_pass_passed: bool
    pass_to_pass_passed: bool
    applied: bool
    patch: str = ""
    note: str = "Compatibility Sample — SWE-bench format, not an official leaderboard instance"


def load_instances(path: str | Path) -> list[SWEBenchInstance]:
    lines = Path(path).read_text().splitlines()
    return [SWEBenchInstance.model_validate_json(ln) for ln in lines if ln.strip()]


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def materialize_instance(instance: SWEBenchInstance, suite_dir: Path, build_root: Path) -> Path:
    if not instance.repo_local:
        raise NotImplementedError(
            "real SWE-bench instance: clone repo@base_commit and reproduce its environment "
            "(see docs/swebench_and_docker.md). Only compatibility samples run locally."
        )
    src = suite_dir / instance.repo_local
    repo = build_root / instance.instance_id.replace("/", "_")
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(src, repo, ignore=_IGNORE)
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "swebench@codeagent.eval"], repo)
    _git(["config", "user.name", "swebench"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", f"base: {instance.instance_id}"], repo)
    return repo


def _apply_patch(worktree: Path, patch_text: str) -> bool:
    if not patch_text.strip():
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(patch_text if patch_text.endswith("\n") else patch_text + "\n")
        patch_file = fh.name
    proc = _git(["apply", "--whitespace=nowarn", patch_file], worktree, check=False)
    Path(patch_file).unlink(missing_ok=True)
    return proc.returncode == 0


def run_instance(
    instance: SWEBenchInstance,
    suite_dir: str | Path,
    *,
    mode: str = "gold",
    provider=None,
    agent_version: str = "v2",
    build_root: str | Path | None = None,
) -> InstanceResult:
    """Run one instance. mode='gold' applies the reference patch; mode='agent' runs the MiniAgent."""
    suite_dir = Path(suite_dir)
    parent = Path(build_root) if build_root else Path(tempfile.mkdtemp(prefix="cae-swe-"))
    repo = materialize_instance(instance, suite_dir, parent)
    try:
        with WorktreeSandbox(repo) as sb:
            # Bring the tests (SWE-bench keeps test_patch separate from the candidate patch).
            if not _apply_patch(sb.root, instance.test_patch):
                return InstanceResult(instance_id=instance.instance_id, mode=mode, resolved=False,
                                      fail_to_pass_passed=False, pass_to_pass_passed=False, applied=False)
            applied = True
            patch_text = ""
            if mode == "gold":
                applied = _apply_patch(sb.root, instance.patch)
                patch_text = instance.patch
            elif mode == "agent":
                if provider is None:
                    raise ValueError("mode='agent' requires a provider")
                task = AgentTask(
                    instruction=instance.problem_statement,
                    workspace_path=str(sb.root),
                    max_steps=25,
                    timeout_seconds=300,
                    project_instructions=_read_agents_md(sb.root),
                )
                trial = MiniAgent(provider, AgentConfig(version=agent_version)).run(
                    task, sb, case_id=instance.instance_id
                )
                patch_text = trial.patch
            else:
                raise ValueError(f"unknown mode: {mode}")

            f2p = run_pytest(sb, instance.fail_to_pass)
            p2p = run_pytest(sb, instance.pass_to_pass)
            resolved = applied and f2p.all_passed and p2p.all_passed
            return InstanceResult(
                instance_id=instance.instance_id, mode=mode, resolved=resolved,
                fail_to_pass_passed=f2p.all_passed, pass_to_pass_passed=p2p.all_passed,
                applied=applied, patch=patch_text,
            )
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _read_agents_md(root: Path) -> str | None:
    p = root / "AGENTS.md"
    return p.read_text() if p.exists() else None
