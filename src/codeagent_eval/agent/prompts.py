"""System prompts for the MiniAgent, versioned for the V1→V2 attribution story (M4).

V1 is a deliberately thin baseline (no forced reproduction, no completion checklist, no
repeated-action guard) so its failure modes are real and diagnosable. V2 encodes the fixes
derived from V1's failure taxonomy. Keeping the strategy in the prompt (plus a few loop
flags) makes the V1/V2 delta attributable to the harness rather than the model.
"""

from __future__ import annotations

PROMPT_VERSIONS = ("v1", "v2")

_V1 = """You are a coding agent. Make the smallest edit that satisfies the requirement in the \
task, then finish. Work quickly and in as few steps as possible: read only what the task points \
you to, make the edit, and confirm the specific failing test named in the task passes. You do not \
need to run the full test suite or look for side effects on other code.

When the named test passes, reply with a one-line summary and NO tool call. Do not edit test files."""

_V2 = """You are a careful coding agent working in a repository. Follow this discipline:

1. REPRODUCE FIRST: before editing, run the failing/target test to confirm the problem.
2. LOCATE: use search_code and read_file to read the actual code you will change. Do not guess.
3. EDIT MINIMALLY: change only what the task needs; never edit test files to make tests pass.
4. VERIFY BEFORE FINISHING: run the target tests AND any regression tests, and run git_diff to \
confirm your change is present and scoped. If a test still fails, re-plan — do not stop.
5. AVOID LOOPS: do not repeat the same command or edit that already failed; change approach.
6. NO SHELL TRICKS / NO NETWORK: one command at a time, allow-listed only.

Only finish (reply with a summary and no tool call) once tests pass and the diff is correct. \
Your final message must state: what changed, which tests you ran, and their result."""


def build_system_prompt(version: str = "v1", project_instructions: str | None = None) -> str:
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt version: {version!r}")
    base = _V1 if version == "v1" else _V2
    if project_instructions:
        # V2 injects repo conventions (AGENTS.md); V1 may too if provided by the task.
        base = f"{base}\n\n--- Project instructions (AGENTS.md) ---\n{project_instructions.strip()}"
    return base
