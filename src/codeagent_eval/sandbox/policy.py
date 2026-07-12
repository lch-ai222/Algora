"""Command allow/deny policy for the process-isolation sandbox.

This is the security boundary for the MVP sandbox (Docker is the "talk-only" upgrade).
The policy is deliberately conservative and *deny-by-default on the executable*: only an
allow-list of well-known, read/build/test commands may run, and a substring denylist
catches destructive or host-escaping patterns even if the base command is allowed.

Honesty note (say this in the demo): true network isolation needs a network namespace /
container. Here "no network" is enforced at the command layer — network tools (curl, wget,
pip install, git push/pull, ssh) are denied — not by a kernel-level firewall.
"""

from __future__ import annotations

import os
import shlex

from pydantic import BaseModel

# Base executables the agent may invoke. Keep this tight; widen deliberately per case.
DEFAULT_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "python", "python3", "pytest", "pyflakes", "ruff", "mypy",
        "ls", "cat", "head", "tail", "wc", "find", "tree", "stat",
        "grep", "egrep", "fgrep", "rg", "diff", "sort", "uniq", "cut",
        "git", "echo", "pwd", "true", "false", "env", "which",
    }
)

# If any of these appears anywhere in the command string, block outright.
DEFAULT_DENIED_SUBSTRINGS: tuple[str, ...] = (
    "rm -rf /", "rm -fr /", "sudo", "shutdown", "reboot", "halt", "poweroff",
    "mkfs", "dd if=", "mount ", "umount", ":(){", "fork()",
    "curl", "wget", "ssh ", "scp ", "sftp", "nc ", "ncat", "telnet",
    "docker", "kubectl", "systemctl", "chmod -r 777", "chown -r",
    "pip install", "pip3 install", "uv pip", "poetry add", "npm install",
    "> /dev/sd", "/etc/passwd", "/etc/shadow",
)

# git subcommands that touch the network or rewrite shared history — denied under no-network.
DENIED_GIT_SUBCOMMANDS: frozenset[str] = frozenset({"push", "pull", "clone", "fetch", "remote"})

# Commands run without a shell (one command each), so operators only matter when they appear
# as their own token after tokenization — e.g. `python a.py && rm b` → the "&&" token. Operators
# glued inside a quoted arg (`python -c "a; b"`) are harmless literals and must not be blocked.
_SHELL_OPERATOR_TOKENS: frozenset[str] = frozenset(
    {"|", "||", "&", "&&", ";", ";;", ">", ">>", "<", "<<", "`"}
)


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    argv: list[str] = []


class CommandPolicy:
    """Decides whether a single command string may run in the sandbox."""

    def __init__(
        self,
        allowed_commands: frozenset[str] = DEFAULT_ALLOWED_COMMANDS,
        denied_substrings: tuple[str, ...] = DEFAULT_DENIED_SUBSTRINGS,
        extra_allowed: frozenset[str] | None = None,
    ):
        self.allowed_commands = allowed_commands | (extra_allowed or frozenset())
        self.denied_substrings = denied_substrings

    def check(self, command: str) -> PolicyDecision:
        text = command.strip()
        if not text:
            return PolicyDecision(allowed=False, reason="empty command")

        lowered = text.lower()
        for needle in self.denied_substrings:
            if needle in lowered:
                return PolicyDecision(allowed=False, reason=f"denied pattern: {needle.strip()!r}")

        try:
            argv = shlex.split(text)
        except ValueError as exc:
            return PolicyDecision(allowed=False, reason=f"unparseable command: {exc}")
        if not argv:
            return PolicyDecision(allowed=False, reason="empty command")

        operator = next((tok for tok in argv if tok in _SHELL_OPERATOR_TOKENS), None)
        if operator is not None:
            return PolicyDecision(
                allowed=False,
                reason=f"shell operator {operator!r} not allowed (one command, no shell)",
            )

        base = os.path.basename(argv[0])
        if base not in self.allowed_commands:
            return PolicyDecision(allowed=False, reason=f"command not in allow-list: {base!r}")

        if base == "git" and len(argv) > 1 and argv[1] in DENIED_GIT_SUBCOMMANDS:
            return PolicyDecision(allowed=False, reason=f"git {argv[1]} denied under no-network policy")

        return PolicyDecision(allowed=True, argv=argv)
