"""W2-7: real SWE-bench instances, and the ways a local harness can silently fake them.

Every test here encodes something that was measured while getting three flask instances to
resolve under their gold patches. None of them needs the network: the failures they pin are in
the matching and bookkeeping, not in the download.

The theme is that a SWE-bench harness fails in the flattering direction. Losing a
PASS_TO_PASS id, importing the wrong copy of the project, or accepting a pytest usage error as
a test failure all make instances *easier* to resolve, so none of them shows up as an obviously
broken run — they show up as a good score.
"""

from __future__ import annotations

import pytest

from codeagent_eval.benchmark.swebench_env import (
    KNOWN_UNSUPPORTED,
    SUPPORTED_REPOS,
    UnsupportedInstance,
    resolve_node_ids,
    spec_for,
)

# A real truncation from SWE-bench Lite's pallets__flask-5063: the published PASS_TO_PASS list
# was derived from wrapped pytest output, so the id stops mid-parameter.
TRUNCATED = 'tests/test_cli.py::test_locate_app[cliapp.factory-create_app2("foo",'
FULL = 'tests/test_cli.py::test_locate_app[cliapp.factory-create_app2("foo", "bar")-app]'


def test_exact_ids_pass_through():
    resolved = resolve_node_ids(["a.py::test_x"], ["a.py::test_x", "a.py::test_y"])
    assert resolved.matched == ("a.py::test_x",)
    assert resolved.repaired == ()
    assert resolved.unmatched == ()


def test_a_truncated_id_is_repaired_when_the_prefix_is_unique():
    resolved = resolve_node_ids([TRUNCATED], [FULL, "tests/test_cli.py::test_other"])
    assert resolved.matched == (FULL,)
    assert resolved.repaired == ((TRUNCATED, FULL),)
    assert resolved.unmatched == ()


def test_an_ambiguous_prefix_is_not_guessed():
    """Two candidates means the harness cannot know which test the oracle meant."""
    other = 'tests/test_cli.py::test_locate_app[cliapp.factory-create_app2("foo", "baz")-app]'
    resolved = resolve_node_ids([TRUNCATED], [FULL, other])
    assert resolved.matched == ()
    assert resolved.unmatched == (TRUNCATED,)


def test_an_id_that_matches_nothing_is_reported_not_dropped():
    """The failure mode this exists to prevent.

    PASS_TO_PASS is a conjunction, so every id quietly discarded makes the instance easier to
    resolve. A shortened oracle has to surface as a distinct outcome, never as a pass.
    """
    resolved = resolve_node_ids(["a.py::gone", "a.py::here"], ["a.py::here"])
    assert resolved.matched == ("a.py::here",)
    assert resolved.unmatched == ("a.py::gone",)


def test_repairs_are_recorded_alongside_the_ids_they_replaced():
    """A repair is a harness decision about the oracle and has to stay auditable."""
    resolved = resolve_node_ids([TRUNCATED, "a.py::test_x"], [FULL, "a.py::test_x"])
    assert dict(resolved.repaired) == {TRUNCATED: FULL}
    assert set(resolved.matched) == {FULL, "a.py::test_x"}


def test_an_empty_oracle_matches_nothing_rather_than_everything():
    resolved = resolve_node_ids(["a.py::test_x"], [])
    assert resolved.matched == ()
    assert resolved.unmatched == ("a.py::test_x",)


# --------------------------------------------------------------------------- #
# Repository recipes
# --------------------------------------------------------------------------- #
def test_every_supported_repo_declares_what_to_uninstall():
    """The project is installed only for its dependencies and then removed.

    Leaving it installed lets its editable .pth win over PYTHONPATH, so every trial imports the
    shared setup tree instead of its own worktree — measured, that made the gold patch
    invisible and reported every instance unresolved.
    """
    for repo, spec in SUPPORTED_REPOS.items():
        assert spec.distribution, f"{repo} must name a distribution to uninstall"


def test_an_unsupported_repo_explains_itself_rather_than_scoring_zero():
    with pytest.raises(UnsupportedInstance, match="vendor urllib3"):
        spec_for("psf/requests")


def test_an_unknown_repo_names_what_is_available():
    with pytest.raises(UnsupportedInstance, match="supported:"):
        spec_for("django/django")


def test_supported_and_unsupported_tables_do_not_overlap():
    """A repository in both would resolve by dictionary order rather than by intent."""
    assert not set(SUPPORTED_REPOS) & set(KNOWN_UNSUPPORTED)


# --------------------------------------------------------------------------- #
# Agent mode
# --------------------------------------------------------------------------- #
def test_the_instruction_never_names_the_hidden_tests():
    """SWE-bench applies test_patch after the agent runs; showing it changes the task."""
    from codeagent_eval.benchmark.swebench_agent import INSTRUCTION

    rendered = INSTRUCTION.format(statement="something is broken", repo="pallets/flask")
    assert "test_patch" not in rendered
    assert "hidden test suite" in rendered


def test_test_paths_are_read_from_the_diff_headers():
    from codeagent_eval.benchmark.swebench_agent import _test_paths

    patch = (
        "diff --git a/tests/test_cli.py b/tests/test_cli.py\n"
        "--- a/tests/test_cli.py\n"
        "+++ b/tests/test_cli.py\n"
        "@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/tests/conftest.py b/tests/conftest.py\n"
        "--- a/tests/conftest.py\n"
        "+++ b/tests/conftest.py\n"
        "@@ -1 +1 @@\n-a\n+b\n"
    )
    assert _test_paths(patch) == {"tests/test_cli.py", "tests/conftest.py"}


def test_an_agent_edit_to_an_oracle_file_is_recorded_rather_than_scored():
    """The oracle is restored before grading, so the edit must survive as a finding.

    Without the record, an agent that rewrote the very tests it is judged by would look
    identical to one that did not — the restore hides the behaviour it protects against.
    """
    from codeagent_eval.benchmark.swebench_agent import InstanceAttempt

    attempt = InstanceAttempt(
        instance_id="x", adapter="mini_agent",
        changed_files=("src/flask/app.py", "tests/test_cli.py"),
        touched_test_files=("tests/test_cli.py",),
    )
    assert attempt.as_dict()["touched_test_files"] == ["tests/test_cli.py"]


def test_an_oracle_file_the_agent_created_is_removed_not_just_checked_out(tmp_path):
    """``git checkout --`` cannot restore a path that does not exist at the base commit.

    The oracle's test_patch both modifies existing files and creates new ones. An agent that
    writes its own file where the patch will add one blocks the patch from applying, so the
    attempt fails as a harness error instead of being graded. Removing untracked files at
    oracle-owned paths is what makes both cases behave the same.
    """
    import subprocess

    from codeagent_eval.benchmark.swebench_agent import _test_paths

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "keep.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    created = repo / "tests" / "static" / "config.toml"
    created.parent.mkdir(parents=True)
    created.write_text("agent = true\n")

    patch = "diff --git a/tests/static/config.toml b/tests/static/config.toml\n" \
            "--- /dev/null\n+++ b/tests/static/config.toml\n@@ -0,0 +1 @@\n+oracle = true\n"
    assert _test_paths(patch) == {"tests/static/config.toml"}

    for path in _test_paths(patch):
        done = subprocess.run(["git", "checkout", "--", path], cwd=repo,
                              capture_output=True, text=True, check=False)
        assert done.returncode != 0, "an untracked path cannot be checked out"
        (repo / path).unlink(missing_ok=True)

    assert not created.exists()
