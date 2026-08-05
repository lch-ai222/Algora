"""Stand-in for the ``cline`` binary so adapter tests exercise the real subprocess path.

Cline splits what the adapter needs across two places — run-level facts on stdout, tool detail
in a session file under ``--data-dir`` — so a useful fake has to write both. Mocking the parse
functions would leave exactly the seam between them untested, which is where an adapter that
counts tool calls but attributes none of them would slip through.

Scenario keys (all optional):
    lines          raw stdout lines, emitted verbatim (malformed JSON allowed on purpose)
    messages       written to <data-dir>/sessions/<id>/<id>.messages.json as Cline would
    edits          {relative_path: contents} written into cwd before streaming
    stderr         text written to stderr
    sleep_s        hang after streaming, to trigger the adapter's wall-clock budget
    spawn_child    {"marker": path, "delay_s": n} — a detached child writing ``marker``;
                   it survives only if the adapter fails to kill the whole process group
    exit_code      process exit status
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_FAKE_FLAGS = ("--fake-scenario", "--fake-dump")


def _arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def _is_fake_flag(argv: list[str], index: int) -> bool:
    """True for a harness-injected flag or the value that follows it."""
    return argv[index] in _FAKE_FLAGS or (index > 0 and argv[index - 1] in _FAKE_FLAGS)


def main(argv: list[str]) -> int:
    # The scenario and argv-dump paths are baked into the shim's argv rather than passed
    # through the environment: the adapter under test scrubs the child environment down to a
    # strict allowlist, and weakening that to make the fake reachable would stop the test
    # exercising the isolation it exists to check.
    scenario_path = _arg(argv, "--fake-scenario")
    dump_path = _arg(argv, "--fake-dump")
    argv = [a for i, a in enumerate(argv) if not _is_fake_flag(argv, i)]

    if "--version" in argv or "-V" in argv:
        sys.stdout.write("3.0.49\n")
        return 0

    scenario = json.loads(Path(scenario_path).read_text()) if scenario_path else {}
    if dump_path:
        Path(dump_path).write_text(
            json.dumps({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}),
            encoding="utf-8",
        )

    if argv and argv[0] == "auth":
        if scenario.get("auth_exit_code"):
            sys.stderr.write("fake auth failure\n")
            return int(scenario["auth_exit_code"])
        sys.stdout.write("Provider configured: openai-compatible\n")
        return 0

    cwd = Path(_arg(argv, "--cwd") or ".")
    data_dir = Path(_arg(argv, "--data-dir") or ".")

    for relative, contents in (scenario.get("edits") or {}).items():
        target = cwd / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")

    messages = scenario.get("messages")
    if messages is not None:
        session_id = scenario.get("session_id", "sess_fake")
        session_dir = data_dir / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / f"{session_id}.messages.json").write_text(
            json.dumps({"version": 1, "sessionId": session_id, "messages": messages}),
            encoding="utf-8",
        )

    child = scenario.get("spawn_child")
    if child:
        subprocess.Popen(
            [
                sys.executable, "-c",
                f"import time,pathlib;time.sleep({child.get('delay_s', 5)});"
                f"pathlib.Path({child['marker']!r}).write_text('survived')",
            ],
            start_new_session=False,
        )

    for line in scenario.get("lines") or []:
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        sys.stdout.flush()
        if scenario.get("line_delay_s"):
            time.sleep(scenario["line_delay_s"])

    if scenario.get("stderr"):
        sys.stderr.write(scenario["stderr"])

    if scenario.get("sleep_s"):
        time.sleep(scenario["sleep_s"])

    return int(scenario.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
