"""The suite's identity is its content, not its name.

Two experiments both recording ``mini_store_long`` were treated as comparable across a change
that added four cases and twenty-two files to the shared repository. A later matrix then
reported 0.875 on the same four case ids where an earlier one reported 0.50, and the
disagreement could not be attributed: sampling and benchmark content had both moved and nothing
on either manifest said so.
"""

from __future__ import annotations

from pathlib import Path

from codeagent_eval.benchmark import suite_fingerprint

SUITE = Path("datasets/mini_store_long")


def test_a_fingerprint_is_stable_across_calls():
    """A value that moves on its own cannot certify anything."""
    assert suite_fingerprint(SUITE) == suite_fingerprint(SUITE)


def _copy(source: Path, destination: Path) -> Path:
    import shutil

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".pytest_cache"))
    return destination


def test_editing_the_shared_repository_changes_the_fingerprint(tmp_path):
    """The change that actually went unnoticed: the cases kept their ids, the repo grew."""
    suite = _copy(SUITE, tmp_path / "suite")
    before = suite_fingerprint(suite)
    (suite / "repo_src" / "mini_store" / "extra_module.py").write_text("VALUE = 1\n")
    assert suite_fingerprint(suite) != before


def test_editing_a_case_definition_changes_the_fingerprint(tmp_path):
    suite = _copy(SUITE, tmp_path / "suite")
    before = suite_fingerprint(suite)
    manifest = suite / "suite.json"
    manifest.write_text(manifest.read_text().replace("long-order-snapshot", "long-order-snap", 1))
    assert suite_fingerprint(suite) != before


def test_build_output_does_not_move_the_fingerprint(tmp_path):
    """Otherwise running the suite once would invalidate every earlier result."""
    suite = _copy(SUITE, tmp_path / "suite")
    before = suite_fingerprint(suite)
    cache = suite / "repo_src" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "mod.cpython-311.pyc").write_bytes(b"\x00\x01")
    assert suite_fingerprint(suite) == before


def test_two_different_suites_do_not_collide():
    assert suite_fingerprint(SUITE) != suite_fingerprint(Path("datasets/mini_store_suite"))
