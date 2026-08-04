#!/usr/bin/env python3
"""Build or replay a sanitized, no-model failure reproduction bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from codeagent_eval.detectors.repro_bundle import (  # noqa: E402
    ReproBundleError,
    build_repro_bundle,
    replay_repro_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a bundle from one trial directory")
    build.add_argument("trial", type=Path)
    build.add_argument("--suite", required=True, type=Path)
    build.add_argument("--out", type=Path, default=Path("artifacts/repro_bundles"))

    replay = commands.add_parser("replay", help="replay a bundle without calling a model")
    replay.add_argument("bundle", type=Path)
    replay.add_argument("--suite", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            destination = build_repro_bundle(args.trial, args.suite, args.out)
            print(destination)
            return 0
        result = replay_repro_bundle(args.bundle, args.suite)
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0 if result.reproduced else 2
    except ReproBundleError as exc:
        print(f"repro bundle error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
