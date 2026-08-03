"""Command-line interface for deterministic pricing checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from mini_store.diagnostics import health_report
from mini_store.output import quote_payload
from mini_store.version import VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini-store")
    subparsers = parser.add_subparsers(dest="command", required=True)
    quote = subparsers.add_parser("quote")
    quote.add_argument("--amount", type=float, required=True)
    quote.add_argument("--items", type=int, required=True)
    quote.add_argument("--tax-rate", type=float, default=0.08)
    quote.add_argument("--json", action="store_true", dest="as_json")
    subparsers.add_parser("doctor")
    subparsers.add_parser("version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(health_report(), sort_keys=True))
        return 0
    if args.command == "version":
        print(VERSION)
        return 0

    payload = quote_payload(args.amount, args.items, tax_rate=args.tax_rate)
    print(json.dumps(payload, sort_keys=True) if args.as_json else f"{payload['total']:.2f}")
    return 0
