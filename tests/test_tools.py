"""M1 tool tests — each of the six tools behaves on a real sandbox, including the
forbidden-path guard and the uniqueness rule for edits."""

from __future__ import annotations

from pathlib import Path

from codeagent_eval.sandbox import WorktreeSandbox
from codeagent_eval.tools import ToolContext, ToolRegistry, default_tools


def _ctx(sandbox: WorktreeSandbox, forbidden=None) -> ToolContext:
    return ToolContext(sandbox=sandbox, forbidden_paths=forbidden or [])


def test_registry_exposes_six_openai_tools():
    reg = ToolRegistry(default_tools())
    schemas = reg.openai_tools()
    assert len(schemas) == 6
    names = {s["function"]["name"] for s in schemas}
    assert names == {"list_files", "search_code", "read_file", "apply_patch", "run_command", "git_diff"}


def test_list_and_read(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        ctx = _ctx(sb)
        listed = reg.dispatch(ctx, "list_files", {"path": "."})
        assert listed.ok and "app.py" in listed.content
        read = reg.dispatch(ctx, "read_file", {"path": "app.py"})
        assert read.ok and "def add" in read.content
        assert "\t" in read.content  # line-numbered


def test_search_code(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        res = reg.dispatch(_ctx(sb), "search_code", {"pattern": r"def add"})
        assert res.ok and "app.py:1:" in res.content


def test_apply_patch_edit_and_run_tests(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        ctx = _ctx(sb)
        edit = reg.dispatch(
            ctx,
            "apply_patch",
            {"path": "app.py", "old_str": "return a - b  # bug: should be +", "new_str": "return a + b"},
        )
        assert edit.ok, edit.content
        run = reg.dispatch(ctx, "run_command", {"command": "pytest -q"})
        assert run.data["exit_code"] == 0, run.content
        diff = reg.dispatch(ctx, "git_diff", {})
        assert "+    return a + b" in diff.content


def test_apply_patch_rejects_forbidden_path(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        ctx = _ctx(sb, forbidden=["test_*.py"])
        res = reg.dispatch(ctx, "apply_patch", {"path": "test_app.py", "old_str": "5", "new_str": "1"})
        assert res.ok is False
        assert res.data.get("forbidden") is True


def test_apply_patch_requires_unique_match(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        ctx = _ctx(sb)
        # "a" appears many times -> not unique
        res = reg.dispatch(ctx, "apply_patch", {"path": "app.py", "old_str": "a", "new_str": "z"})
        assert res.ok is False and "not unique" in res.content


def test_run_command_blocked_surfaces_reason(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        res = reg.dispatch(_ctx(sb), "run_command", {"command": "curl http://x"})
        assert res.ok is False and res.data.get("blocked") is True


def test_unknown_tool_and_bad_args_do_not_crash(git_repo: Path):
    with WorktreeSandbox(git_repo) as sb:
        reg = ToolRegistry(default_tools())
        ctx = _ctx(sb)
        assert reg.dispatch(ctx, "nope", {}).ok is False
        assert reg.dispatch(ctx, "read_file", {"wrong": "arg"}).ok is False
