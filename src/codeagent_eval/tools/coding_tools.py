"""The six coding tools the MiniAgent uses inside a sandbox.

Read-only tools (list_files / search_code / read_file) touch the filesystem directly via
the sandbox's path guard. The mutating tool (apply_patch) enforces the forbidden-path
policy. run_command routes through the sandbox's command policy + timeout. git_diff
surfaces the current patch. Design goal: reliable, token-frugal primitives an LLM can
drive without shell tricks.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from codeagent_eval.sandbox.worktree import SandboxError
from codeagent_eval.tools.base import Tool, ToolContext, ToolResult

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
_MAX_LISTED = 500
_MAX_SEARCH_RESULTS = 60
_TEXT_SUFFIXES = {".py", ".txt", ".md", ".cfg", ".ini", ".toml", ".json", ".yaml", ".yml", ""}


def _is_forbidden(rel: str, forbidden: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in forbidden)


class ListFilesTool(Tool):
    name = "list_files"
    description = "List files under a workspace-relative directory (recursively). Use to orient yourself."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory relative to workspace root. Default '.'."}
        },
    }

    def run(self, ctx: ToolContext, path: str = ".") -> ToolResult:
        try:
            base = ctx.sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(ok=False, content=str(exc))
        if not base.exists():
            return ToolResult(ok=False, content=f"no such path: {path}")
        root = ctx.sandbox.root.resolve()
        found: list[str] = []
        for p in sorted(base.rglob("*")):
            if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            if p.is_file():
                found.append(str(p.relative_to(root)))
            if len(found) >= _MAX_LISTED:
                break
        listing = "\n".join(found) or "(empty)"
        return ToolResult(ok=True, content=listing, data={"count": len(found)})


class SearchCodeTool(Tool):
    name = "search_code"
    description = "Search file contents by regular expression (ripgrep-style). Returns file:line: matches."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {"type": "string", "description": "Directory to search. Default '.'."},
        },
        "required": ["pattern"],
    }

    def run(self, ctx: ToolContext, pattern: str, path: str = ".") -> ToolResult:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(ok=False, content=f"invalid regex: {exc}")
        try:
            base = ctx.sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(ok=False, content=str(exc))
        root = ctx.sandbox.root.resolve()
        hits: list[str] = []
        for p in sorted(base.rglob("*")):
            if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            if not p.is_file() or p.suffix not in _TEXT_SUFFIXES:
                continue
            try:
                for i, line in enumerate(p.read_text(errors="replace").splitlines(), start=1):
                    if regex.search(line):
                        hits.append(f"{p.relative_to(root)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= _MAX_SEARCH_RESULTS:
                            break
            except OSError:
                continue
            if len(hits) >= _MAX_SEARCH_RESULTS:
                break
        content = "\n".join(hits) if hits else "(no matches)"
        return ToolResult(ok=True, content=content, data={"matches": len(hits)})


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a file with line numbers, paginated. Read before you edit."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File relative to workspace root."},
            "start": {"type": "integer", "description": "1-based start line. Default 1."},
            "limit": {"type": "integer", "description": "Max lines to return. Default page size."},
        },
        "required": ["path"],
    }

    def run(self, ctx: ToolContext, path: str, start: int = 1, limit: int | None = None) -> ToolResult:
        limit = limit or ctx.page_size
        try:
            target = ctx.sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(ok=False, content=str(exc))
        if not target.is_file():
            return ToolResult(ok=False, content=f"no such file: {path}")
        lines = target.read_text(errors="replace").splitlines()
        start = max(1, start)
        window = lines[start - 1 : start - 1 + limit]
        numbered = "\n".join(f"{start + i}\t{ln}" for i, ln in enumerate(window))
        more = start - 1 + limit < len(lines)
        footer = f"\n…[{len(lines) - (start - 1 + limit)} more lines]" if more else ""
        return ToolResult(
            ok=True,
            content=numbered + footer if numbered else "(empty file)",
            data={"total_lines": len(lines), "read_path": path},
        )


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Edit a file by replacing an exact snippet. Pass old_str (must match exactly once) and new_str. "
        "To create/overwrite a file, pass an empty old_str and the full content in new_str. "
        "Editing forbidden paths (e.g. tests) is rejected."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File relative to workspace root."},
            "old_str": {"type": "string", "description": "Exact text to replace; empty to create/overwrite."},
            "new_str": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_str", "new_str"],
    }

    def run(self, ctx: ToolContext, path: str, old_str: str, new_str: str) -> ToolResult:
        rel = path.lstrip("./")
        if _is_forbidden(rel, ctx.forbidden_paths):
            return ToolResult(
                ok=False,
                content=f"editing {path} is forbidden by task constraints",
                data={"forbidden": True, "path": rel},
            )
        try:
            target = ctx.sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(ok=False, content=str(exc))

        if old_str == "":
            target.parent.mkdir(parents=True, exist_ok=True)
            created = not target.exists()
            target.write_text(new_str)
            verb = "created" if created else "overwrote"
            return ToolResult(ok=True, content=f"{verb} {path} ({len(new_str.splitlines())} lines)",
                              data={"path": rel, "created": created})

        if not target.is_file():
            return ToolResult(ok=False, content=f"no such file: {path}")
        text = target.read_text()
        count = text.count(old_str)
        if count == 0:
            return ToolResult(ok=False, content=f"old_str not found in {path}")
        if count > 1:
            return ToolResult(ok=False, content=f"old_str is not unique in {path} ({count} matches); add context")
        target.write_text(text.replace(old_str, new_str, 1))
        return ToolResult(ok=True, content=f"edited {path}", data={"path": rel})


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run one allow-listed command in the workspace (e.g. `pytest -q`, `python -c ...`). "
        "No shell operators or network. Returns exit code, stdout, stderr."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "A single command, no pipes/redirects."},
            "timeout": {"type": "integer", "description": "Seconds before the command is killed."},
        },
        "required": ["command"],
    }

    def run(self, ctx: ToolContext, command: str, timeout: int | None = None) -> ToolResult:
        result = ctx.sandbox.run(command, timeout=timeout or ctx.default_timeout)
        if result.blocked:
            return ToolResult(ok=False, content=f"command blocked: {result.block_reason}",
                              data={"blocked": True, "block_reason": result.block_reason})
        if result.timed_out:
            return ToolResult(ok=False, content=f"command timed out after {timeout or ctx.default_timeout}s",
                              data={"timed_out": True})
        body = (
            f"exit_code={result.exit_code}\n"
            f"--- stdout ---\n{result.stdout or '(empty)'}\n"
            f"--- stderr ---\n{result.stderr or '(empty)'}"
        )
        return ToolResult(
            ok=result.exit_code == 0,
            content=body,
            data={
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
            },
        )


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Show the current patch (unified diff of all your changes vs the base commit)."
    parameters = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> ToolResult:
        diff = ctx.sandbox.export_patch()
        return ToolResult(
            ok=True,
            content=diff or "(no changes yet)",
            data={"changed_files": ctx.sandbox.changed_files()},
        )


def default_tools(*, planning: bool = False, memory: bool = False,
                  repo_memory: bool = False) -> list[Tool]:
    """The MiniAgent's toolset.

    Optional tools are off by default so V1/V2 keep exactly the six tools their calibrated
    baselines were measured with; V3 opts in, and each addition can be ablated independently.
    """
    tools: list[Tool] = [
        ListFilesTool(),
        SearchCodeTool(),
        ReadFileTool(),
        ApplyPatchTool(),
        RunCommandTool(),
        GitDiffTool(),
    ]
    if planning:
        from codeagent_eval.tools.planning_tools import UpdatePlanTool

        tools.append(UpdatePlanTool())
    if memory:
        from codeagent_eval.tools.memory_tools import UpdateScratchpadTool

        tools.append(UpdateScratchpadTool())
    if repo_memory:
        from codeagent_eval.tools.memory_tools import RememberRepoTool

        tools.append(RememberRepoTool())
    return tools


# convenience for path handling in graders/tests
def workspace_relative(root: Path, target: Path) -> str:
    return str(target.relative_to(root))
