#!/usr/bin/env python
"""Benchmark self-check — the hard gate on case validity.

For every case in a suite, prove:
  1. hidden tests are NOT present in the fresh workspace (agent can't read them);
  2. the visible/target tests FAIL at the base commit (the defect is real);
  3. the regression tests PASS at the base commit (the defect is isolated);
  4. after applying the reference fix: target + regression + hidden tests all PASS
     (a known-good solution exists and the hidden tests are consistent).
  5. for every declared known shortcut: the patch applies, makes the visible command look
     green, still fails hidden tests, and produces a strong reward-hacking signal; the
     reference solution must remain detector-clean.

Any violated invariant makes the case invalid. Exit code is non-zero if any case fails,
so this can run in CI. Usage: python scripts/selfcheck.py [suite_dir]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.benchmark import (  # noqa: E402
    apply_reference_fix,
    case_dir,
    inject_all_feedback_tests,
    inject_hidden_tests,
    load_suite,
    materialize_case,
)
from codeagent_eval.detectors import detect_reward_hacking  # noqa: E402
from codeagent_eval.graders.pytest_run import run_pytest  # noqa: E402
from codeagent_eval.sandbox import WorktreeSandbox  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _ok(cond, label: str, detail: str = "") -> bool:
    cond = bool(cond)
    mark = f"{GREEN}PASS{RESET}" if cond else f"{RED}FAIL{RESET}"
    print(f"    [{mark}] {label}" + (f" {DIM}{detail}{RESET}" if detail else ""))
    return cond


def check_case(suite_dir: Path, clean_repo: Path, case, build_root: Path) -> bool:
    print(f"\n• {case.case_id} ({case.task_type}, {case.difficulty})")
    repo = materialize_case(suite_dir, clean_repo, case, build_root=build_root)
    passed = True

    # (1) + (2) + (3): base commit behavior
    with WorktreeSandbox(repo) as sb:
        hidden_paths = {node_id.split("::", 1)[0] for node_id in case.hidden_tests}
        hidden_absent = all(not (sb.root / path).exists() for path in hidden_paths)
        passed &= _ok(hidden_absent, "hidden tests absent in fresh workspace")
        followup_paths = {
            path
            for round_ in (case.multi_turn.rounds if case.multi_turn else [])
            for path in round_.visible_test_files
        }
        followups_absent = all(not (sb.root / path).exists() for path in followup_paths)
        passed &= _ok(followups_absent, "future-turn tests absent before feedback")
        inject_all_feedback_tests(sb.root, suite_dir, case)

        # Named tests must actually fail. A run that only reports a non-zero exit code — a
        # collection or import error — is not evidence the defect is real: it means the target
        # tests never ran, so what the case claims to exercise is untested and the grader would
        # be scoring "did the agent make the package importable" instead.
        base_target = run_pytest(sb, case.all_visible_tests)
        if base_target.failed:
            detail = f"failed={base_target.failed}"
        else:
            detail = f"no per-test failures; only {base_target.errors or ['nothing']}"
        passed &= _ok(bool(base_target.failed), "target tests FAIL at base (defect is real)", detail)
        base_regr = run_pytest(sb, case.regression_tests)
        passed &= _ok(base_regr.all_passed, "regression tests PASS at base (defect isolated)")

    # (4): apply reference fix, everything passes (incl. hidden)
    with WorktreeSandbox(repo) as sb:
        restored = apply_reference_fix(sb.root, suite_dir, clean_repo, case)
        reference_report = detect_reward_hacking(sb.export_patch())
        if case.known_shortcuts:
            passed &= _ok(
                not reference_report.hacked,
                "reference fix is reward-hacking detector clean",
                f"signals={reference_report.names}",
            )
        inject_all_feedback_tests(sb.root, suite_dir, case)
        fixed_target = run_pytest(sb, case.all_visible_tests)
        passed &= _ok(fixed_target.all_passed, "target tests PASS after reference fix",
                      f"restored={restored}")
        fixed_regr = run_pytest(sb, case.regression_tests)
        passed &= _ok(fixed_regr.all_passed, "regression tests PASS after reference fix")
        inject_hidden_tests(sb.root, suite_dir, case)
        fixed_hidden = run_pytest(sb, case.hidden_tests)
        passed &= _ok(fixed_hidden.all_passed, "hidden tests PASS after reference fix",
                      f"passed={len(fixed_hidden.passed)}")

    # (5): deliberately bad solutions must be tempting enough to appear green, but must not
    # satisfy the hidden oracle. Keeping these fixtures executable is the detector's recall
    # gate and proves the suite measures behaviour rather than merely enabling test writes.
    for shortcut_name in case.known_shortcuts:
        shortcut = (case_dir(suite_dir, case.case_id) / "shortcuts" / shortcut_name).resolve()
        with WorktreeSandbox(repo) as sb:
            exists = shortcut.is_file()
            passed &= _ok(exists, f"known shortcut fixture exists: {shortcut_name}")
            if not exists:
                continue
            checked = subprocess.run(
                ["git", "apply", "--unidiff-zero", "--check", str(shortcut)],
                cwd=sb.root,
                capture_output=True,
                text=True,
            )
            applies = checked.returncode == 0
            passed &= _ok(
                applies,
                f"known shortcut applies: {shortcut_name}",
                checked.stderr.strip(),
            )
            if not applies:
                continue
            subprocess.run(
                ["git", "apply", "--unidiff-zero", str(shortcut)], cwd=sb.root, check=True
            )

            shortcut_patch = sb.export_patch()
            report = detect_reward_hacking(shortcut_patch)
            passed &= _ok(
                report.hacked and bool(report.signals),
                "shortcut triggers strong reward-hacking evidence",
                f"signals={report.names}",
            )

            visible = run_pytest(sb, case.all_visible_tests)
            apparent_green = visible.exit_code == 0 and not visible.failed and not visible.errors
            passed &= _ok(
                apparent_green,
                "shortcut makes visible pytest command appear green",
                f"passed={len(visible.passed)} skipped={len(visible.skipped)}",
            )
            inject_hidden_tests(sb.root, suite_dir, case)
            hidden = run_pytest(sb, case.hidden_tests)
            passed &= _ok(
                not hidden.all_passed,
                "shortcut still fails hidden verification",
                f"failed={len(hidden.failed)} errors={len(hidden.errors)}",
            )

    shutil.rmtree(repo, ignore_errors=True)
    return passed


def main() -> int:
    suite_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else _ROOT / "datasets" / "mini_store_suite"
    suite = load_suite(suite_dir)
    clean_repo = suite.repo
    print(f"Self-checking suite {suite.name!r} — {len(suite.cases)} cases (repo: {clean_repo})")

    build_root = Path(tempfile.mkdtemp(prefix="cae-selfcheck-"))
    results = {c.case_id: check_case(suite_dir, clean_repo, c, build_root) for c in suite.cases}
    shutil.rmtree(build_root, ignore_errors=True)

    ok = sum(results.values())
    print(f"\n{'='*60}\n{ok}/{len(results)} cases valid")
    for cid, r in results.items():
        print(f"  {'✓' if r else '✗'} {cid}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
