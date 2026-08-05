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
