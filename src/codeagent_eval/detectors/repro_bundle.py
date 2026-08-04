"""Build and replay portable diagnostics for deterministic trial failures.

The bundle carries the agent patch and sanitized evidence, but deliberately excludes hidden
tests and native adapter logs. Replay materializes the case from the shipped suite, applies
the captured patch, injects hidden tests at grade time, and invokes the same graders as the
runner. No model call is involved.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import EvalCase, inject_hidden_tests, load_suite, materialize_case
from codeagent_eval.detectors.context_amnesia import detect_context_amnesia
from codeagent_eval.detectors.instruction_drift import detect_instruction_drift
from codeagent_eval.detectors.reward_hacking import detect_reward_hacking
from codeagent_eval.graders import GradeResult, combine, grade_constraints, grade_patch, grade_tests
from codeagent_eval.models import TraceEventType, utc_now_iso
from codeagent_eval.sandbox import WorktreeSandbox

BUNDLE_SCHEMA = "algora.repro_bundle.v1"
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|auth[_-]?token|access[_-]?token|authorization|credential|secret|password)"
    r"(?:$|[_-])",
    re.I,
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:(?:bearer|sk|zai)[-_ ]?)[a-z0-9][a-z0-9._-]{11,}"
)
_PATCH_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|auth[_-]?token|access[_-]?token|authorization|password)"
    r"\s*[:=]\s*['\"]?[a-z0-9._-]{12,}"
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_REPLAY_EVENTS = {TraceEventType.COMMAND_FINISH, TraceEventType.TEST_RESULT}
_REQUIRED_BUNDLE_FILES = {
    "config.json",
    "detector-findings.json",
    "failure-tags.json",
    "grader-summary.json",
    "patch.diff",
    "replay-fixture.json",
    "trial-summary.json",
}


class ReproBundleError(ValueError):
    """The source artifact is unsafe or incomplete for deterministic reproduction."""


class ReplayResult(BaseModel):
    bundle_id: str
    case_id: str
    suite_fingerprint_match: bool | None
    reproduced: bool
    expected_signature: dict[str, Any]
    actual_signature: dict[str, Any] | None = None
    error: str | None = None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ReproBundleError(f"unreadable JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ReproBundleError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _redact(value: Any) -> tuple[Any, int]:
    """Redact credential-shaped JSON values while retaining diagnostic structure."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)) and item not in (None, "", False, 0):
                cleaned[key] = "[REDACTED]"
                count += 1
            else:
                cleaned[key], found = _redact(item)
                count += found
        return cleaned, count
    if isinstance(value, list):
        cleaned_list = []
        count = 0
        for item in value:
            cleaned, found = _redact(item)
            cleaned_list.append(cleaned)
            count += found
        return cleaned_list, count
    if isinstance(value, str):
        cleaned, count = _SECRET_VALUE.subn("[REDACTED]", value)
        return cleaned, count
    return value, 0


def _suite_fingerprint(suite_dir: Path, case: EvalCase) -> str:
    """Hash the case definition, its private overlays, and the clean repository.

    Only the aggregate digest enters the bundle. Hidden filenames and contents never do.
    """
    suite = load_suite(suite_dir)
    digest = hashlib.sha256()
    case_payload = _json_text(case.model_dump(mode="json")).encode()
    digest.update(b"case.json\0" + case_payload)

    roots = [suite_dir / "cases" / case.case_id, Path(suite.repo)]
    for root_index, root in enumerate(roots):
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
            relative = path.relative_to(root).as_posix()
            if any(part in {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
                   for part in path.parts):
                continue
            digest.update(f"{root_index}:{relative}\0".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _project_commit(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _project_relative(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return path.resolve().relative_to(Path(result.stdout.strip()).resolve()).as_posix()
    except ValueError:
        return None


def grade_signature(grade: GradeResult | dict[str, Any]) -> dict[str, Any]:
    """Stable regression signature; excludes pytest text and hidden node identifiers."""
    payload = grade.model_dump(mode="json") if isinstance(grade, GradeResult) else grade
    test = payload["test"]
    constraint = payload["constraint"]
    patch = payload["patch"]
    return {
        "task_success": payload["task_success"],
        "strict_success": payload["strict_success"],
        "tests": {
            "target_passed": test["target_passed"],
            "regression_passed": test["regression_passed"],
            "hidden_passed": test["hidden_passed"],
            "functional_success": test["functional_success"],
        },
        "constraint": {
            "passed": constraint["passed"],
            "violations": constraint["violations"],
        },
        "patch": {
            "has_patch": patch["has_patch"],
            "applies_cleanly": patch["applies_cleanly"],
            "changed_files": patch["changed_files"],
            "modified_tests": patch["modified_tests"],
            "passed": patch["passed"],
        },
    }


def _outcome_summary(outcome: dict[str, Any], *, hidden: bool) -> dict[str, Any]:
    """Keep counts and status, never hidden test names or raw failure output."""
    return {
        "collected": outcome.get("collected", 0),
        "passed_count": len(outcome.get("passed", [])),
        "failed_count": len(outcome.get("failed", [])),
        "error_count": len(outcome.get("errors", [])),
        "skipped_count": len(outcome.get("skipped", [])),
        "exit_code": outcome.get("exit_code"),
        "timed_out": outcome.get("timed_out", False),
        "blocked": outcome.get("blocked", False),
        "details_omitted": hidden,
    }


def _grader_summary(grade: dict[str, Any]) -> dict[str, Any]:
    test = grade["test"]
    return {
        "case_id": grade["case_id"],
        "signature": grade_signature(grade),
        "test_outcomes": {
            "target": _outcome_summary(test["target"], hidden=False),
            "regression": _outcome_summary(test["regression"], hidden=False),
            "hidden": _outcome_summary(test["hidden"], hidden=True),
        },
    }


def _assert_no_hidden_identifiers(root: Path, case: EvalCase) -> None:
    """Fail closed if any generated text names a hidden test artifact."""
    markers = set(case.hidden_test_files)
    markers.update(selector.split("::", 1)[0] for selector in case.hidden_tests)
    markers.update(Path(marker).name for marker in list(markers))
    markers.discard("")
    for path in root.iterdir():
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        if any(marker in content for marker in markers):
            raise ReproBundleError(
                f"generated diagnostic {path.name!r} contains a hidden-test identifier"
            )


def _read_trial(trial_dir: Path) -> TrialResult | None:
    trial_file = trial_dir / "trial.json"
    trajectory_file = trial_dir / "trajectory.jsonl"
    if not trial_file.is_file() or not trajectory_file.is_file():
        return None
    try:
        payload = _load_json(trial_file)
        payload["events"] = [
            json.loads(line)
            for line in trajectory_file.read_text().splitlines()
            if line.strip()
        ]
        return TrialResult.model_validate(payload)
    except (OSError, ValueError):
        return None


def _trial_summary(trial: TrialResult) -> dict[str, Any]:
    return {
        "stop_reason": trial.stop_reason,
        "canonical_stop_reason": trial.canonical_stop_reason,
        "steps": trial.steps,
        "tool_call_count": trial.tool_call_count,
        "final_message": trial.final_message,
        "prompt_tokens": trial.prompt_tokens,
        "completion_tokens": trial.completion_tokens,
        "cost_usd": trial.cost_usd,
        "cost_source": trial.cost_source,
        "completion_checks": trial.completion_checks,
        "plan": trial.plan,
        "started_at": trial.started_at,
        "finished_at": trial.finished_at,
        "duration_ms": trial.duration_ms,
    }


def _replay_fixture(trial: TrialResult | None) -> dict[str, Any]:
    if trial is None:
        # Legacy artifacts cannot reproduce constraints that depend on whether tests ran or
        # which commands were attempted. Keep the limitation explicit rather than inventing it.
        return {"supported": False, "reason": "trial.json or trajectory.jsonl is missing"}
    events = [event.model_dump(mode="json") for event in trial.events if event.type in _REPLAY_EVENTS]
    return {
        "supported": True,
        "trial": {
            "stop_reason": trial.stop_reason,
            "canonical_stop_reason": trial.canonical_stop_reason,
            "completion_checks": {"ran_tests": bool(trial.completion_checks.get("ran_tests"))},
            "events": events,
        },
    }


def _detector_findings(case: EvalCase, patch: str, trial: TrialResult | None,
                       changed_files: list[str]) -> dict[str, Any]:
    findings: dict[str, Any] = {
        "reward_hacking": detect_reward_hacking(patch).model_dump(mode="json"),
        "instruction_drift": None,
        "context_amnesia": None,
    }
    if trial is not None:
        findings["instruction_drift"] = detect_instruction_drift(
            case, trial, changed_files
        ).model_dump(mode="json")
        findings["context_amnesia"] = detect_context_amnesia(case, trial).model_dump(mode="json")
    return findings


def build_repro_bundle(trial_dir: str | Path, suite_dir: str | Path,
                       out_root: str | Path) -> Path:
    """Create a non-overwriting reproduction directory and return its path."""
    trial_dir = Path(trial_dir).resolve()
    suite_dir = Path(suite_dir).resolve()
    out_root = Path(out_root)
    for name in ("config.json", "patch.diff", "grader-results.json", "failure-tags.json"):
        if not (trial_dir / name).is_file():
            raise ReproBundleError(f"missing required artifact: {trial_dir / name}")

    config = _load_json(trial_dir / "config.json")
    grade = _load_json(trial_dir / "grader-results.json")
    failure = _load_json(trial_dir / "failure-tags.json")
    case_id = str(config.get("case_id") or grade.get("case_id") or trial_dir.parent.name)
    recorded_case_ids = {value for value in (config.get("case_id"), grade.get("case_id"),
                                              failure.get("case_id")) if value is not None}
    if recorded_case_ids != {case_id}:
        raise ReproBundleError(f"artifact case_id mismatch: {sorted(recorded_case_ids)}")
    if grade.get("strict_success") is True:
        raise ReproBundleError("the source trial is a strict success, not a defect to reproduce")
    if failure.get("primary") == "ENVIRONMENT":
        raise ReproBundleError("infrastructure failures are not deterministic agent defects")

    suite = load_suite(suite_dir)
    try:
        case = next(item for item in suite.cases if item.case_id == case_id)
    except StopIteration as exc:
        raise ReproBundleError(f"case {case_id!r} is not present in suite {suite.name!r}") from exc

    patch = (trial_dir / "patch.diff").read_text(errors="replace")
    if _SECRET_VALUE.search(patch) or _PATCH_SECRET.search(patch):
        raise ReproBundleError("patch contains credential-shaped text; refusing to copy it")
    trial = _read_trial(trial_dir)
    changed_files = list(grade.get("patch", {}).get("changed_files", []))
    fixture = _replay_fixture(trial)

    experiment_id = trial_dir.parents[1].name if len(trial_dir.parents) >= 2 else "experiment"
    bundle_id = _SAFE_ID.sub("-", f"{experiment_id}-{case_id}-{trial_dir.name}").strip("-")
    destination = out_root / bundle_id
    if destination.exists():
        raise ReproBundleError(f"bundle already exists; refusing to overwrite: {destination}")
    out_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".repro-", dir=out_root))

    redactions = 0
    try:
        (staging / "patch.diff").write_text(patch)
        for name, value in {
            "config.json": config,
            "failure-tags.json": failure,
            "grader-summary.json": _grader_summary(grade),
            "detector-findings.json": _detector_findings(case, patch, trial, changed_files),
            "replay-fixture.json": fixture,
            "trial-summary.json": _trial_summary(trial) if trial is not None else {
                "unavailable": "legacy artifact has no trial.json"
            },
        }.items():
            cleaned, found = _redact(value)
            redactions += found
            (staging / name).write_text(_json_text(cleaned))

        trajectory = trial_dir / "trajectory.jsonl"
        if trajectory.is_file():
            cleaned_events = []
            for line in trajectory.read_text(errors="replace").splitlines():
                if not line.strip():
                    continue
                cleaned, found = _redact(json.loads(line))
                redactions += found
                cleaned_events.append(json.dumps(cleaned, sort_keys=True, ensure_ascii=False))
            (staging / "trajectory.jsonl").write_text("\n".join(cleaned_events) + "\n")

        _assert_no_hidden_identifiers(staging, case)
        files = {path.name: _sha256(path) for path in sorted(staging.iterdir()) if path.is_file()}
        suite_path = _project_relative(suite_dir)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "bundle_id": bundle_id,
            "created_at": utc_now_iso(),
            "source": {
                "experiment_id": experiment_id,
                "case_id": case_id,
                "repeat": trial_dir.name,
                "project_commit": _project_commit(suite_dir),
            },
            "suite": {
                "name": suite.name,
                "path": suite_path,
                "fingerprint_sha256": _suite_fingerprint(suite_dir, case),
            },
            "expected_signature": grade_signature(grade),
            "replay": {
                "supported": fixture["supported"],
                "command": "python scripts/build_repro_bundle.py replay <bundle-dir>",
            },
            "security": {
                "hidden_tests_embedded": False,
                "hidden_test_details_embedded": False,
                "native_trajectory_embedded": False,
                "redactions": redactions,
            },
            "files": files,
        }
        (staging / "manifest.json").write_text(_json_text(manifest))
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def _load_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest = _load_json(bundle_dir / "manifest.json")
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise ReproBundleError(f"unsupported bundle schema: {manifest.get('schema')!r}")
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ReproBundleError("bundle manifest files must be an object")
    missing = _REQUIRED_BUNDLE_FILES - set(files)
    if missing:
        raise ReproBundleError(f"bundle manifest omits required checksums: {sorted(missing)}")
    for name, expected in files.items():
        if Path(name).name != name:
            raise ReproBundleError(f"unsafe bundle file path: {name!r}")
        path = bundle_dir / name
        if not path.is_file() or _sha256(path) != expected:
            raise ReproBundleError(f"bundle checksum mismatch: {name}")
    return manifest


def replay_repro_bundle(bundle_dir: str | Path, suite_dir: str | Path | None = None) -> ReplayResult:
    """Replay a bundle with no model and compare its deterministic grade signature."""
    bundle_dir = Path(bundle_dir).resolve()
    manifest = _load_manifest(bundle_dir)
    fixture = _load_json(bundle_dir / "replay-fixture.json")
    expected = manifest["expected_signature"]
    case_id = manifest["source"]["case_id"]
    if not fixture.get("supported"):
        return ReplayResult(
            bundle_id=manifest["bundle_id"], case_id=case_id,
            suite_fingerprint_match=None, reproduced=False, expected_signature=expected,
            error=fixture.get("reason", "replay unsupported"),
        )

    if suite_dir is None:
        recorded = manifest.get("suite", {}).get("path")
        if not recorded:
            raise ReproBundleError("bundle has no project-relative suite path; pass --suite")
        project = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=bundle_dir,
            capture_output=True, text=True, check=False,
        )
        if project.returncode != 0:
            raise ReproBundleError("cannot resolve project root; pass --suite")
        project_root = Path(project.stdout.strip()).resolve()
        candidate = (project_root / recorded).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ReproBundleError("recorded suite path escapes the project root") from exc
        suite_dir = candidate
    suite_dir = Path(suite_dir).resolve()
    suite = load_suite(suite_dir)
    try:
        case = next(item for item in suite.cases if item.case_id == case_id)
    except StopIteration as exc:
        raise ReproBundleError(f"case {case_id!r} is absent from suite {suite.name!r}") from exc

    fingerprint_match = _suite_fingerprint(suite_dir, case) == manifest["suite"]["fingerprint_sha256"]
    if not fingerprint_match:
        return ReplayResult(
            bundle_id=manifest["bundle_id"], case_id=case_id,
            suite_fingerprint_match=False, reproduced=False, expected_signature=expected,
            error="suite fingerprint changed; refusing to compare different oracles",
        )

    trial = TrialResult.model_validate(fixture["trial"])
    patch = (bundle_dir / "patch.diff").read_text()
    with tempfile.TemporaryDirectory(prefix="cae-replay-") as tmp:
        repo = materialize_case(suite_dir, suite.repo, case, build_root=Path(tmp) / "build")
        with WorktreeSandbox(repo) as sandbox:
            if patch.strip():
                applied = subprocess.run(
                    ["git", "apply", "--whitespace=nowarn", "-"], cwd=sandbox.root,
                    input=patch, capture_output=True, text=True, check=False,
                )
                if applied.returncode != 0:
                    return ReplayResult(
                        bundle_id=manifest["bundle_id"], case_id=case_id,
                        suite_fingerprint_match=True, reproduced=False,
                        expected_signature=expected, error=f"patch apply failed: {applied.stderr.strip()}",
                    )
            changed_files = sandbox.changed_files()
            captured_patch = sandbox.export_patch()
            inject_hidden_tests(sandbox.root, suite_dir, case)
            grade = combine(
                case.case_id,
                grade_tests(sandbox, case),
                grade_constraints(case, trial, changed_files, captured_patch),
                grade_patch(captured_patch, changed_files, base_repo=repo),
            )
    actual = grade_signature(grade)
    return ReplayResult(
        bundle_id=manifest["bundle_id"], case_id=case_id,
        suite_fingerprint_match=True, reproduced=actual == expected,
        expected_signature=expected, actual_signature=actual,
        error=None if actual == expected else "deterministic grade signature changed",
    )
