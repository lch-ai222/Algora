"""W3-4: a captured failure can be diagnosed and replayed without a model call."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import inject_hidden_tests, load_suite, materialize_case
from codeagent_eval.detectors.repro_bundle import (
    ReproBundleError,
    build_repro_bundle,
    replay_repro_bundle,
)
from codeagent_eval.failure_taxonomy import attribute_failure
from codeagent_eval.graders import combine, grade_constraints, grade_patch, grade_tests
from codeagent_eval.runner import _persist_trial, run_experiment
from codeagent_eval.sandbox import WorktreeSandbox

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "datasets" / "mini_store_suite"
CASE_ID = "bugfix-cart-merge"


def test_cli_is_directly_executable_from_the_checkout():
    result = subprocess.run(
        [sys.executable, "scripts/build_repro_bundle.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "build" in result.stdout and "replay" in result.stdout


@pytest.fixture(scope="module")
def failed_trial(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The deterministic none baseline is a real failed trial and costs no API quota."""
    out_root = tmp_path_factory.mktemp("runs")
    summary = run_experiment(
        "none", SUITE, None, repeats=1, case_filter=[CASE_ID], out_root=out_root
    )
    return out_root / summary["experiment_id"] / CASE_ID / "rep0"


@pytest.fixture(scope="module")
def patched_failed_trial(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Produce a valid, non-empty no-op patch whose functional tests still fail."""
    root = tmp_path_factory.mktemp("patched-run")
    suite = load_suite(SUITE)
    case = next(item for item in suite.cases if item.case_id == CASE_ID)
    repo = materialize_case(SUITE, suite.repo, case, build_root=root / "build")
    trial = TrialResult(stop_reason="final", completion_checks={"ran_tests": False})
    with WorktreeSandbox(repo) as sandbox:
        source = sandbox.root / "mini_store" / "cart.py"
        source.write_text(source.read_text() + "\n# diagnostic no-op\n")
        patch = sandbox.export_patch()
        changed_files = sandbox.changed_files()
        trial.patch = patch
        trial.changed_files = changed_files
        inject_hidden_tests(sandbox.root, SUITE, case)
        grade = combine(
            case.case_id,
            grade_tests(sandbox, case),
            grade_constraints(case, trial, changed_files, patch),
            grade_patch(patch, changed_files, base_repo=repo),
        )
    destination = root / "experiment" / CASE_ID / "rep0"
    _persist_trial(
        destination,
        {"agent": "fixture", "case_id": CASE_ID, "task_type": case.task_type},
        trial,
        grade,
        attribute_failure(case, trial, grade),
    )
    return destination


def test_bundle_excludes_hidden_details_and_native_logs(tmp_path: Path, failed_trial: Path):
    bundle = build_repro_bundle(failed_trial, SUITE, tmp_path / "bundles")
    manifest = json.loads((bundle / "manifest.json").read_text())

    assert manifest["security"] == {
        "hidden_tests_embedded": False,
        "hidden_test_details_embedded": False,
        "native_trajectory_embedded": False,
        "redactions": 0,
    }
    assert not (bundle / "native").exists()
    all_text = "\n".join(path.read_text() for path in bundle.iterdir() if path.is_file())
    assert "test_hidden_cart.py" not in all_text
    assert "raw_tail" not in (bundle / "grader-summary.json").read_text()


@pytest.mark.slow
def test_no_model_replay_reproduces_the_grade_signature(tmp_path: Path, failed_trial: Path):
    bundle = build_repro_bundle(failed_trial, SUITE, tmp_path / "bundles")
    result = replay_repro_bundle(bundle, SUITE)

    assert result.suite_fingerprint_match is True
    assert result.reproduced is True
    assert result.actual_signature == result.expected_signature
    assert result.actual_signature["task_success"] is False


@pytest.mark.slow
def test_replay_applies_a_nonempty_failed_patch(
    tmp_path: Path, patched_failed_trial: Path
):
    bundle = build_repro_bundle(patched_failed_trial, SUITE, tmp_path / "bundles")
    assert (bundle / "patch.diff").read_text().strip()

    result = replay_repro_bundle(bundle, SUITE)

    assert result.reproduced is True
    assert result.actual_signature["patch"]["has_patch"] is True
    assert result.actual_signature["patch"]["changed_files"] == ["mini_store/cart.py"]


def test_checksum_tampering_is_rejected(tmp_path: Path, failed_trial: Path):
    bundle = build_repro_bundle(failed_trial, SUITE, tmp_path / "bundles")
    (bundle / "failure-tags.json").write_text("{}\n")

    with pytest.raises(ReproBundleError, match="checksum mismatch"):
        replay_repro_bundle(bundle, SUITE)


def test_required_checksum_cannot_be_removed_from_the_manifest(
    tmp_path: Path, failed_trial: Path
):
    bundle = build_repro_bundle(failed_trial, SUITE, tmp_path / "bundles")
    manifest_file = bundle / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["files"].pop("patch.diff")
    manifest_file.write_text(json.dumps(manifest))

    with pytest.raises(ReproBundleError, match="omits required checksums"):
        replay_repro_bundle(bundle, SUITE)


def test_suite_fingerprint_change_is_not_misreported_as_a_regression(
    tmp_path: Path, failed_trial: Path
):
    bundle = build_repro_bundle(failed_trial, SUITE, tmp_path / "bundles")
    manifest_file = bundle / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["suite"]["fingerprint_sha256"] = "0" * 64
    manifest_file.write_text(json.dumps(manifest))

    result = replay_repro_bundle(bundle, SUITE)

    assert result.suite_fingerprint_match is False
    assert result.reproduced is False
    assert "different oracles" in result.error


def test_bundle_never_overwrites_an_existing_diagnostic(tmp_path: Path, failed_trial: Path):
    out = tmp_path / "bundles"
    destination = build_repro_bundle(failed_trial, SUITE, out)

    with pytest.raises(ReproBundleError, match="refusing to overwrite"):
        build_repro_bundle(failed_trial, SUITE, out)

    assert destination.is_dir()


def test_credential_shaped_patch_is_rejected(tmp_path: Path, failed_trial: Path):
    unsafe = tmp_path / "unsafe-trial"
    shutil.copytree(failed_trial, unsafe)
    (unsafe / "patch.diff").write_text(
        "diff --git a/config.py b/config.py\n--- a/config.py\n+++ b/config.py\n"
        "@@ -0,0 +1 @@\n+TOKEN = '" + "sk-" + "abcdefghijklmnop'\n"
    )

    with pytest.raises(ReproBundleError, match="credential-shaped"):
        build_repro_bundle(unsafe, SUITE, tmp_path / "bundles")


def test_structured_secret_is_redacted_without_erasing_token_metrics(
    tmp_path: Path, failed_trial: Path
):
    source = tmp_path / "redaction" / CASE_ID / "rep0"
    shutil.copytree(failed_trial, source)
    config_file = source / "config.json"
    config = json.loads(config_file.read_text())
    config.update({"max_tokens": 4096, "ANTHROPIC_AUTH_TOKEN": "real-looking-secret"})
    config_file.write_text(json.dumps(config))

    bundle = build_repro_bundle(source, SUITE, tmp_path / "bundles")
    cleaned = json.loads((bundle / "config.json").read_text())

    assert cleaned["max_tokens"] == 4096
    assert cleaned["ANTHROPIC_AUTH_TOKEN"] == "[REDACTED]"
    assert json.loads((bundle / "manifest.json").read_text())["security"]["redactions"] == 1


def test_legacy_trial_builds_diagnostic_but_refuses_invented_replay(
    tmp_path: Path, failed_trial: Path
):
    legacy = tmp_path / "legacy" / CASE_ID / "rep0"
    shutil.copytree(failed_trial, legacy)
    (legacy / "trial.json").unlink()
    (legacy / "trajectory.jsonl").unlink()
    bundle = build_repro_bundle(legacy, SUITE, tmp_path / "bundles")

    result = replay_repro_bundle(bundle, SUITE)

    assert result.reproduced is False
    assert "missing" in result.error
