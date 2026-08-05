#!/usr/bin/env python
"""Validate or solve real SWE-bench Lite instances locally.

    python scripts/run_swebench_official.py --mode gold          # environment check, no model
    python scripts/run_swebench_official.py --mode gold --instance psf__requests-2148

``gold`` applies the reference patch and requires FAIL_TO_PASS to flip while PASS_TO_PASS
holds. It calls no model, so it measures the *environment* rather than any agent — an instance
that does not resolve under gold cannot be scored against an agent, because a failure there is
indistinguishable from a dependency that no longer installs.

Instances come from ``datasets/swebench_lite/instances.jsonl`` in the official schema. Only
repositories with a recipe in ``swebench_env.SUPPORTED_REPOS`` can be built here; anything else
is reported as unsupported rather than unresolved.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.benchmark.swebench import SWEBenchInstance  # noqa: E402
from codeagent_eval.benchmark.swebench_env import (  # noqa: E402
    DEFAULT_CACHE,
    UnsupportedInstance,
    build_environment,
    checkout_worktree,
    collect_node_ids,
    resolve_node_ids,
    run_node_ids,
    spec_for,
)

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
DEFAULT_INSTANCES = _ROOT / "datasets" / "swebench_lite" / "instances.jsonl"


def load(path: Path) -> list[SWEBenchInstance]:
    return [
        SWEBenchInstance.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def apply_patch(worktree: Path, patch: str) -> bool:
    if not patch.strip():
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as handle:
        handle.write(patch if patch.endswith("\n") else patch + "\n")
        name = handle.name
    done = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", name],
        cwd=str(worktree), capture_output=True, text=True, check=False,
    )
    Path(name).unlink(missing_ok=True)
    return done.returncode == 0


def run_gold(instance: SWEBenchInstance, cache: Path) -> dict[str, object]:
    spec = spec_for(instance.repo)
    version = getattr(instance, "version", None) or "unknown"
    env = build_environment(spec, version, instance.environment_setup_commit or instance.base_commit, cache)

    worktree = Path(cache) / "work" / instance.instance_id
    checkout_worktree(spec, instance.base_commit, worktree, cache)
    try:
        if not apply_patch(worktree, instance.test_patch):
            return {"instance_id": instance.instance_id, "status": "test_patch_failed"}

        # Dataset ids are matched against what pytest can actually collect, because several
        # are truncated at a line wrap in the published data. Repairs and misses are reported;
        # dropping a PASS_TO_PASS id would make the instance easier to resolve.
        files = {i.split("::", 1)[0] for i in instance.fail_to_pass + instance.pass_to_pass}
        collected = collect_node_ids(env, worktree, files)
        f2p_ids = resolve_node_ids(instance.fail_to_pass, collected)
        p2p_ids = resolve_node_ids(instance.pass_to_pass, collected)
        if f2p_ids.unmatched:
            return {
                "instance_id": instance.instance_id, "status": "f2p_ids_unmatched",
                "unmatched": list(f2p_ids.unmatched),
            }

        # Before the fix the target tests must fail; otherwise the instance proves nothing.
        pre_ok, _, _ = run_node_ids(env, worktree, list(f2p_ids.matched))
        if pre_ok:
            return {"instance_id": instance.instance_id, "status": "f2p_already_passing"}

        if not apply_patch(worktree, instance.patch):
            return {"instance_id": instance.instance_id, "status": "gold_patch_failed"}

        f2p_ok, f2p_out, _ = run_node_ids(env, worktree, list(f2p_ids.matched))
        p2p_ok, p2p_out, p2p_code = run_node_ids(env, worktree, list(p2p_ids.matched))
        # PASS_TO_PASS is a conjunction, so an id that could not be matched is a weakened
        # oracle rather than a detail. Such an instance gets its own status: counting it as
        # resolved would report a pass against a test set the harness never actually ran.
        if f2p_ok and p2p_ok:
            status = "resolved_weak_oracle" if p2p_ids.unmatched else "resolved"
        else:
            status = "unresolved"
        return {
            "instance_id": instance.instance_id,
            "status": status,
            "fail_to_pass": f2p_ok,
            "pass_to_pass": p2p_ok,
            "n_f2p": len(instance.fail_to_pass),
            "n_p2p": len(instance.pass_to_pass),
            "p2p_ran": len(p2p_ids.matched),
            "p2p_repaired": [list(pair) for pair in p2p_ids.repaired],
            "p2p_unmatched": list(p2p_ids.unmatched),
            "pytest_usage_error": p2p_code == 4,
            "environment": env.manifest(),
            "tail": (f2p_out if not f2p_ok else p2p_out)[-1200:] if not (f2p_ok and p2p_ok) else "",
        }
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=["gold"], default="gold")
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--instance", action="append", default=[], help="filter by instance_id")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    instances = load(args.instances)
    if args.instance:
        wanted = set(args.instance)
        unknown = wanted - {i.instance_id for i in instances}
        if unknown:
            print(f"unknown instance ids: {sorted(unknown)}", file=sys.stderr)
            return 2
        instances = [i for i in instances if i.instance_id in wanted]

    results: list[dict[str, object]] = []
    for instance in instances:
        try:
            result = run_gold(instance, args.cache)
        except UnsupportedInstance as exc:
            result = {"instance_id": instance.instance_id, "status": "unsupported", "detail": str(exc)}
        except (subprocess.TimeoutExpired, OSError) as exc:
            result = {"instance_id": instance.instance_id, "status": "error", "detail": str(exc)[:300]}
        results.append(result)

        status = str(result["status"])
        colour = GREEN if status == "resolved" else (YELLOW if status in ("unsupported",) else RED)
        detail = ""
        if status == "unresolved":
            detail = f"F2P={result.get('fail_to_pass')} P2P={result.get('pass_to_pass')}"
        elif status.startswith("resolved"):
            miss = len(result.get("p2p_unmatched") or ())
            fix = len(result.get("p2p_repaired") or ())
            detail = f"F2P={result.get('n_f2p')} P2P={result.get('p2p_ran')}/{result.get('n_p2p')}"
            if fix:
                detail += f" (repaired {fix})"
            if miss:
                detail += f" (UNMATCHED {miss} — oracle shortened)"
        elif status in ("unsupported", "error"):
            detail = str(result.get("detail", ""))[:90]
        print(f"  [{colour}{status:<20}{RESET}] {instance.instance_id:<24} {DIM}{detail}{RESET}")

    resolved = sum(1 for r in results if r["status"] == "resolved")
    weak = sum(1 for r in results if r["status"] == "resolved_weak_oracle")
    buildable = sum(1 for r in results if r["status"] not in ("unsupported", "error"))
    print(f"\ngold: {resolved}/{buildable} buildable instances resolved on the full oracle"
          f"{f', {weak} more only against a shortened one' if weak else ''} "
          f"({len(results) - buildable} unsupported or errored)")
    if weak:
        print("A shortened oracle makes resolution easier, so those are reported separately")
        print("rather than folded into the rate.")
    if resolved < buildable:
        print("An instance that does not resolve under gold cannot be scored against an agent:")
        print("a failure there is the environment, not the agent.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2, default=str))
        print(f"wrote {args.json}")
    return 0 if resolved + weak == buildable else 1


if __name__ == "__main__":
    raise SystemExit(main())
