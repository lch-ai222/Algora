"""Running an external coding-agent CLI under a budget, without losing the evidence.

Extracted from the Claude Code adapter when a second external framework arrived and needed
the same three things. They are worth stating, because each one exists because of a way a
trial can end up unattributable:

**Stream to disk as it arrives.** A trial killed at its wall clock is exactly the trial you
most want to read, and it is the one that has produced no final output. Writing every line
through during the run makes the partial trajectory durable before the process is signalled.

**Kill the whole process group.** Agents spawn pytest, node, compilers. Signalling only the
parent leaves children mutating the worktree while the patch is being exported, which turns
a timeout into a corrupted diff.

**Never fail silently on malformed output.** Lines that are not JSON objects are counted, not
dropped, so a parser disagreement shows up as a number instead of a quietly shorter trajectory.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: How long to wait for a signalled process, and for its output readers, before escalating.
GRACE_PERIOD_S = 5


@dataclass
class ProcessOutcome:
    records: list[dict[str, Any]]
    malformed_lines: int
    stderr: str
    returncode: int | None
    timed_out: bool
    launch_error: str | None = None


def terminate_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole group, then SIGKILL.

    Child tools (pytest, node) must die too — a survivor would keep mutating the worktree
    while the patch is being exported.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, AttributeError):
        pgid = None

    def signal_group(sig: int) -> None:
        if pgid is not None and hasattr(os, "killpg"):
            try:
                os.killpg(pgid, sig)
                return
            except OSError:
                pass
        try:
            proc.send_signal(sig)
        except OSError:
            pass

    signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=GRACE_PERIOD_S)
        return
    except subprocess.TimeoutExpired:
        pass
    signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=GRACE_PERIOD_S)
    except subprocess.TimeoutExpired:
        pass


def stream_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    deadline_s: float,
    raw_log: Path,
    append: bool = False,
) -> ProcessOutcome:
    """Run a CLI to completion or to ``deadline_s``, persisting stdout to ``raw_log`` live."""
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    malformed = 0
    stderr_chunks: list[str] = []

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return ProcessOutcome([], 0, "", None, False, launch_error=str(exc))

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)

    def drain_stdout(sink) -> None:
        nonlocal malformed
        assert proc.stdout is not None
        for line in proc.stdout:
            sink.write(line if line.endswith("\n") else line + "\n")
            sink.flush()
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(payload, dict):
                records.append(payload)
            else:
                malformed += 1

    with raw_log.open("a" if append else "w", encoding="utf-8") as sink:
        out_thread = threading.Thread(target=drain_stdout, args=(sink,), daemon=True)
        err_thread = threading.Thread(target=drain_stderr, daemon=True)
        out_thread.start()
        err_thread.start()

        timed_out = False
        try:
            proc.wait(timeout=deadline_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_group(proc)

        # Bounded join: readers exit once the pipes close after process death.
        out_thread.join(timeout=GRACE_PERIOD_S)
        err_thread.join(timeout=GRACE_PERIOD_S)

    return ProcessOutcome(
        records=records,
        malformed_lines=malformed,
        stderr="".join(stderr_chunks),
        returncode=proc.returncode,
        timed_out=timed_out,
    )
