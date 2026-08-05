#!/usr/bin/env python3
"""Generate offline JSON, Markdown, and HTML reports from Algora experiments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.report import (  # noqa: E402
    ReportError,
    build_report_data,
    write_static_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiments", nargs="+", type=Path)
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--labels", nargs="*")
    parser.add_argument("--title", default="Algora Cross-Agent Evaluation Report")
    parser.add_argument("--resamples", type=int, default=10_000)
    args = parser.parse_args(argv)
    try:
        report = build_report_data(
            args.experiments, args.suite, labels=args.labels, resamples=args.resamples
        )
        destination = write_static_report(report, args.out, title=args.title)
    except ReportError as exc:
        print(f"report error: {exc}", file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
