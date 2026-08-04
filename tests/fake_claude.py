"""Stand-in for the ``claude`` binary so adapter tests exercise the real subprocess path.

Mocking ``subprocess`` would leave the parts most likely to break untested: incremental
NDJSON draining, wall-clock enforcement, process-group termination and environment
scrubbing. This script is a real executable driven by a JSON scenario file, so those paths
run for real against deterministic output.

Scenario keys (all optional):
    lines             raw stdout lines, emitted verbatim (malformed JSON is allowed on purpose)
    line_delay_s      pause between lines
    edits             {relative_path: contents} written into cwd before streaming
    stderr            text written to stderr
    sleep_s           hang after streaming, to trigger the adapter's wall-clock budget
    spawn_child       {"marker": path, "delay_s": n} — a detached child that writes ``marker``;
                      it survives only if the adapter fails to kill the whole process group
    exit_code         process exit status
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(os.environ.get("CLAUDE_FAKE_VERSION", "1.2.3 (Claude Code)"))
        return 0

    dump = os.environ.get("CLAUDE_FAKE_DUMP")
    if dump:
        Path(dump).write_text(
            json.dumps({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}),
            encoding="utf-8",
        )

    script_path = os.environ.get("CLAUDE_FAKE_SCRIPT")
    if not script_path:
        sys.stderr.write("CLAUDE_FAKE_SCRIPT is not set\n")
        return 1
    scenario = json.loads(Path(script_path).read_text(encoding="utf-8"))

    for rel, content in (scenario.get("edits") or {}).items():
        target = Path(os.getcwd()) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    child = scenario.get("spawn_child")
    if child:
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time,pathlib,sys;time.sleep(float(sys.argv[1]));"
                "pathlib.Path(sys.argv[2]).write_text('survived')",
                str(child["delay_s"]),
                child["marker"],
            ]
        )

    delay = float(scenario.get("line_delay_s", 0) or 0)
    for line in scenario.get("lines", []):
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        sys.stdout.flush()
        if delay:
            time.sleep(delay)

    if scenario.get("stderr"):
        sys.stderr.write(scenario["stderr"])
        sys.stderr.flush()

    hang = float(scenario.get("sleep_s", 0) or 0)
    if hang:
        time.sleep(hang)
    return int(scenario.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
