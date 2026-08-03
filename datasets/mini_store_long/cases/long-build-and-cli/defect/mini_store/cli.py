"""Command-line interface for deterministic pricing checks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini-store")
    subparsers = parser.add_subparsers(dest="command", required=True)
    quote = subparsers.add_parser("quote")
    quote.add_argument("--amount", type=float, required=True)
    quote.add_argument("--items", type=int, required=True)
    quote.add_argument("--tax-rate", type=float, default=0.08)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Broken legacy behavior: ignores item-count discounts and treats the rate as a flat fee.
    print(f"{args.amount + args.tax_rate:.2f}")
    return 0
