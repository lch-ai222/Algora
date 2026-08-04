"""The sales tax rate must have exactly one definition in the package.

Two copies of a constant are not a style problem: they diverge, and a divergence between the
rate an ``Order`` records and the rate ``pricing`` charges is invisible until a refund is
computed against the wrong one.

The direction of the dependency is not free either. ``models`` is the dependency-free base that
``pricing`` imports, so the constant has to live in ``models`` and be re-exported — the reverse
would be a circular import.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mini_store import cli, models, pricing
from mini_store.models import Order

_PACKAGE = Path(models.__file__).parent


def test_pricing_re_exports_the_rate_rather_than_declaring_its_own() -> None:
    assert pricing.DEFAULT_TAX_RATE == models.DEFAULT_TAX_RATE


def test_an_order_defaults_to_the_shared_rate() -> None:
    assert Order(order_id="O-1").tax_rate == models.DEFAULT_TAX_RATE


def test_the_cli_default_is_the_shared_rate() -> None:
    args = cli.build_parser().parse_args(["quote", "--amount", "100", "--items", "1"])
    assert args.tax_rate == models.DEFAULT_TAX_RATE


def test_the_rate_is_written_as_a_literal_in_exactly_one_module() -> None:
    """Whoever owns the constant may spell it out; nobody else may.

    Parsed rather than grepped, so that a docstring explaining the rate is not mistaken for a
    second definition of it — and so the check cannot be satisfied by reformatting a comment.
    """
    offenders = sorted(
        path.name
        for path in _PACKAGE.glob("*.py")
        if path.name != "models.py"
        and any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, float)
            and node.value == models.DEFAULT_TAX_RATE
            for node in ast.walk(ast.parse(path.read_text()))
        )
    )
    assert offenders == [], f"tax rate hardcoded outside models.py: {offenders}"
