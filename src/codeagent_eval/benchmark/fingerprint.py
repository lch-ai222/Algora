"""A content hash for a benchmark suite, so two results can be told apart.

An experiment recorded its suite by name. Two runs both saying ``mini_store_long`` were taken
as comparable, and for a while they were — until the suite grew from four cases to eight and
its shared repository gained twenty-two files. A later matrix then reported 0.875 on the same
four case ids where an earlier one had reported 0.50, and the difference could not be
attributed: sampling and benchmark content had both moved, and nothing on either manifest said
so.

Naming a suite is not identifying it. This hashes what a run actually saw — the case
definitions and every file of the clean repository — so a comparison spanning a change to
either has something to notice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Directories whose contents are build output rather than benchmark definition.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
_SKIP_SUFFIXES = (".pyc", ".pyo")


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in _SKIP_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def suite_fingerprint(suite_dir: str | Path) -> str:
    """Hash the suite definition and its clean repository together.

    Both matter and neither is sufficient. Case definitions alone miss a change to the shared
    repository, which is what silently altered the task; the repository alone misses a case
    being added, retired or rewritten.
    """
    suite_dir = Path(suite_dir)
    digest = hashlib.sha256()
    for path in _iter_files(suite_dir):
        digest.update(str(path.relative_to(suite_dir)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
