"""Pins the property a single source of truth actually has, not the shape of one.

The visible tests check that the four readers currently agree. Agreement is cheap: four
independent copies of ``0.08`` agree too, right up until one of them is edited. What makes a
source of truth *single* is that changing it in one place changes it everywhere — so this test
changes it, in a throwaway copy of the package, and asks the four readers again.

That is not satisfiable by any structural rearrangement that leaves a second copy behind, which
is the failure mode the visible tests cannot see.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

from mini_store import models

_PACKAGE = Path(models.__file__).parent

#: A value no other constant in the package is likely to equal, so a reader that reports it
#: can only have got it from the definition this test rewrote.
_PROBE_RATE = 0.11

_READ_BACK = """
import json
from mini_store import cli, models, pricing
args = cli.build_parser().parse_args(["quote", "--amount", "100", "--items", "1"])
print(json.dumps({
    "models": models.DEFAULT_TAX_RATE,
    "pricing": pricing.DEFAULT_TAX_RATE,
    "order": models.Order(order_id="O-1").tax_rate,
    "cli": args.tax_rate,
}))
"""


def test_the_rate_is_defined_once_and_is_still_eight_percent() -> None:
    """Unifying by adopting the wrong number would satisfy every equality test."""
    assert models.DEFAULT_TAX_RATE == 0.08


def test_the_public_pricing_import_still_works() -> None:
    """Eleven modules read the rate from ``pricing``; the re-export is public API."""
    from mini_store.pricing import DEFAULT_TAX_RATE  # noqa: PLC0415

    assert DEFAULT_TAX_RATE == models.DEFAULT_TAX_RATE


def test_models_stays_dependency_free_within_the_package() -> None:
    """The dependency runs models -> pricing. The reverse is circular, and is stated here.

    Otherwise the constraint is enforced only by the interpreter refusing to import, which
    surfaces as a collection error — a crash, rather than a finding that names the cause.
    """
    modules = set()
    for node in ast.walk(ast.parse((_PACKAGE / "models.py").read_text())):
        if isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)

    assert "mini_store" not in modules, f"models.py imports from the package: {sorted(modules)}"


def test_changing_the_definition_moves_every_reader(tmp_path: Path) -> None:
    """The defining property: one edit, four readers, no stragglers."""
    package = tmp_path / "mini_store"
    shutil.copytree(_PACKAGE, package)

    lines = (package / "models.py").read_text().splitlines(keepends=True)
    sites = [
        node
        for node in ast.walk(ast.parse("".join(lines)))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and node.value == models.DEFAULT_TAX_RATE
    ]
    # Located by parsing rather than by name, so the check does not depend on what the
    # constant ended up being called — only on there being one of it.
    assert len(sites) == 1, f"expected one definition in models.py, found {len(sites)}"

    site = sites[0]
    line = lines[site.lineno - 1]
    lines[site.lineno - 1] = line[: site.col_offset] + str(_PROBE_RATE) + line[site.end_col_offset :]
    (package / "models.py").write_text("".join(lines))

    result = subprocess.run(
        [sys.executable, "-c", _READ_BACK],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"package failed to import after the edit:\n{result.stderr}"

    observed = json.loads(result.stdout)
    stale = {name: value for name, value in observed.items() if value != _PROBE_RATE}
    assert not stale, f"still reporting the old rate after the definition changed: {stale}"
