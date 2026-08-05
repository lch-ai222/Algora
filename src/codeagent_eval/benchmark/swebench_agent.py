"""Letting a coding agent attempt a real SWE-bench instance, under this project's contracts.

The official protocol is what makes a number here comparable to a published one, and two parts
of it are easy to break in a direction that flatters the agent:

**The tests are not shown.** SWE-bench gives the agent a problem statement and a repository at
``base_commit``; ``test_patch`` is applied afterwards, at grading time. An agent that can read
the failing tests is solving a different, much easier task, so the tests stay out of the
workspace exactly as this project's own suites keep their hidden oracle out.

**Grading happens in a fresh checkout.** The agent's patch is exported, then replayed onto a
clean worktree together with ``test_patch``. Grading in the workspace the agent just used would
let a stray file, an uncommitted edit, or a modified test file decide the outcome. It also
means an agent that edited the very test files ``test_patch`` touches cannot corrupt the
oracle: those paths are restored before the patch is applied, and the fact is recorded as a
finding rather than silently repaired.

Everything else — budgets, trajectory normalization, cost provenance — comes from the
``AgentAdapter`` protocol, so all four supported frameworks run the same instance the same way.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeagent_eval.adapters import AgentRunResult, BudgetContract, create_adapter
from codeagent_eval.benchmark.swebench import SWEBenchInstance
from codeagent_eval.benchmark.swebench_env import (
    BuiltEnvironment,
    build_environment,
    checkout_worktree,
    collect_node_ids,
    resolve_node_ids,
    run_node_ids,
    spec_for,
)
from codeagent_eval.models import AgentTask
from codeagent_eval.sandbox import WorktreeSandbox

#: Instruction wrapper. Deliberately thin: the problem statement is the task, and adding
#: guidance here would change what is being measured between frameworks.
INSTRUCTION = """{statement}

You are working in a checkout of {repo} at an earlier commit. Fix the issue described above by
editing the library source. Do not add dependencies. There is a hidden test suite; make the
described behaviour correct rather than guessing at test names."""


@dataclass
class InstanceAttempt:
    """One agent attempt at one instance, with the evidence needed to interpret it."""

    instance_id: str
    adapter: str
    resolved: bool = False
    fail_to_pass: bool = False
    pass_to_pass: bool = False
    weak_oracle: bool = False
    patch: str = ""
    changed_files: tuple[str, ...] = ()
    #: Test files the agent modified. SWE-bench restores them before grading, so this is a
    #: reward-hacking observation rather than something that affects the score.
    touched_test_files: tuple[str, ...] = ()
    stop_reason: str = ""
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_call_count: int = 0
    steps: int = 0
    error: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "adapter": self.adapter,
            "resolved": self.resolved,
            "fail_to_pass": self.fail_to_pass,
            "pass_to_pass": self.pass_to_pass,
            "weak_oracle": self.weak_oracle,
            "changed_files": list(self.changed_files),
            "touched_test_files": list(self.touched_test_files),
            "stop_reason": self.stop_reason,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tool_call_count": self.tool_call_count,
            "steps": self.steps,
            "error": self.error,
            "environment": self.environment,
        }


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def _apply(worktree: Path, patch: str) -> bool:
    if not patch.strip():
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as handle:
        handle.write(patch if patch.endswith("\n") else patch + "\n")
        name = handle.name
    done = _git(["apply", "--whitespace=nowarn", name], worktree)
    Path(name).unlink(missing_ok=True)
    return done.returncode == 0


def _test_paths(patch: str) -> set[str]:
    """Files a diff touches, read from its ``+++`` headers."""
    paths = set()
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line[6:].strip())
    return paths


def _standalone_repo(source: Path, destination: Path) -> Path:
    """Copy a checkout into its own git repository.

    The instance checkout is a worktree of a shared clone, and handing that to the sandbox
    would let one trial's commits reach the clone every other trial reads.
    """
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--depth", "1",
         f"file://{source}", str(destination)],
        capture_output=True, text=True, check=False,
    )
    if not (destination / ".git").exists():
        raise RuntimeError(f"failed to isolate {source} into {destination}")
    _git(["config", "user.email", "swebench@algora.eval"], destination)
    _git(["config", "user.name", "algora"], destination)
    return destination


def attempt_instance(
    instance: SWEBenchInstance,
    *,
    adapter_name: str,
    cache: Path,
    wall_clock_s: int = 600,
    max_steps: int = 40,
    provider=None,
    harness: str = "v3",
    adapter_config=None,
    max_completion_tokens: int = 4096,
    work_root: Path | None = None,
) -> InstanceAttempt:
    """Run one adapter against one instance and grade it the way SWE-bench does."""
    spec = spec_for(instance.repo)
    env = build_environment(
        spec, instance.version, instance.environment_setup_commit or instance.base_commit, cache
    )
    attempt = InstanceAttempt(
        instance_id=instance.instance_id, adapter=adapter_name, environment=env.manifest()
    )

    root = Path(work_root or (Path(cache) / "agent"))
    root.mkdir(parents=True, exist_ok=True)
    checkout = checkout_worktree(spec, instance.base_commit, root / f"{instance.instance_id}-src", cache)
    repo = _standalone_repo(checkout, root / f"{instance.instance_id}-repo")

    try:
        result = _run_adapter(
            instance, adapter_name, repo, env, spec.source_dir,
            wall_clock_s=wall_clock_s, max_steps=max_steps, provider=provider,
            harness=harness, adapter_config=adapter_config,
            max_completion_tokens=max_completion_tokens,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        attempt.error = f"{type(exc).__name__}: {exc}"[:400]
        return attempt

    attempt.patch = result.patch
    attempt.changed_files = tuple(result.changed_files)
    attempt.stop_reason = result.stop_reason
    attempt.duration_ms = result.duration_ms
    attempt.prompt_tokens = result.prompt_tokens
    attempt.completion_tokens = result.completion_tokens
    attempt.tool_call_count = result.tool_call_count
    attempt.steps = result.steps
    attempt.touched_test_files = tuple(sorted(_test_paths(instance.test_patch) & set(result.changed_files)))

    grade(instance, attempt, env, spec, cache, root)
    return attempt


def _run_adapter(
    instance: SWEBenchInstance, adapter_name: str, repo: Path, env: BuiltEnvironment,
    source_dir: str, *, wall_clock_s: int, max_steps: int, provider, harness: str,
    adapter_config, max_completion_tokens: int,
) -> AgentRunResult:
    adapter = create_adapter(
        adapter_name, provider=provider, harness=harness,
        max_completion_tokens=max_completion_tokens, config=adapter_config,
    )
    probe = adapter.probe()
    if not probe.available:
        raise RuntimeError(probe.detail or f"adapter {adapter_name} unavailable")

    task = AgentTask(
        instruction=INSTRUCTION.format(statement=instance.problem_statement, repo=instance.repo),
        workspace_path=str(repo),
        case_id=instance.instance_id,
        max_steps=max_steps,
        timeout_seconds=wall_clock_s,
    )
    budget = BudgetContract(max_wall_clock_s=wall_clock_s, max_steps=max_steps)
    with WorktreeSandbox(repo) as sandbox:
        # PYTHONPATH must name the sandbox's own worktree, not the repository it was cut from:
        # the sandbox checks out a fresh copy, so pointing at the parent leaves the agent
        # unable to import the project it is editing. Measured, that made every command fail
        # with ModuleNotFoundError while the agent kept editing — it worked blind, and blind
        # attempts across arms would have looked like a uniformly hard benchmark.
        sandbox.extra_env.update({
            "PATH": f"{env.python.parent}:/usr/bin:/bin",
            "PYTHONPATH": str(sandbox.root / source_dir) if source_dir else str(sandbox.root),
        })
        adapter.prepare(sandbox.root, task, budget, runtime=sandbox)
        try:
            return adapter.run(task.instruction)
        finally:
            adapter.cleanup()


def grade(instance: SWEBenchInstance, attempt: InstanceAttempt, env: BuiltEnvironment,
          spec, cache: Path, root: Path) -> None:
    """Replay the agent's patch onto a clean checkout and apply the official oracle."""
    graded = checkout_worktree(spec, instance.base_commit, root / f"{instance.instance_id}-grade", cache)

    if attempt.patch.strip() and not _apply(graded, attempt.patch):
        attempt.error = "agent patch did not apply to a clean checkout"
        return
    # Restore anything the test patch owns, so an agent that edited those files cannot change
    # the oracle. The edit itself is already recorded on the attempt.
    #
    # Two cases, and only handling the first leaves a hole. Files the patch *modifies* exist at
    # base and are restored by checkout. Files it *creates* do not, so checkout cannot touch
    # them — and an agent that created its own file at that path makes test_patch fail to
    # apply. Measured: Cline wrote tests/static/config.toml on flask-4992, exactly where the
    # oracle adds one, which turned a gradeable attempt into a harness error. Removing an
    # untracked file at an oracle-owned path closes it, and the edit stays on the record.
    for path in _test_paths(instance.test_patch):
        restored = _git(["checkout", "--", path], graded)
        if restored.returncode != 0:
            (graded / path).unlink(missing_ok=True)
    if not _apply(graded, instance.test_patch):
        attempt.error = "test_patch did not apply after the agent's changes"
        return

    files = {i.split("::", 1)[0] for i in instance.fail_to_pass + instance.pass_to_pass}
    collected = collect_node_ids(env, graded, files)
    f2p = resolve_node_ids(instance.fail_to_pass, collected)
    p2p = resolve_node_ids(instance.pass_to_pass, collected)
    if f2p.unmatched:
        attempt.error = f"FAIL_TO_PASS ids unmatched: {list(f2p.unmatched)[:2]}"
        return

    attempt.fail_to_pass, _, _ = run_node_ids(env, graded, list(f2p.matched))
    attempt.pass_to_pass, _, _ = run_node_ids(env, graded, list(p2p.matched))
    attempt.weak_oracle = bool(p2p.unmatched)
    attempt.resolved = attempt.fail_to_pass and attempt.pass_to_pass
