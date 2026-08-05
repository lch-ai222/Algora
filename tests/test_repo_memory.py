"""W3-2: memory that outlives a run, and the guard that keeps it from faking a result.

Cross-run memory is the half of "memory management" the mainstream agents have and this project
did not. Inside a benchmark it is also the one capability that can manufacture its own evidence:
the suites reuse one repository across many cases, so a note written while solving a case and
read back while solving that same case is not memory working, it is the answer leaking. The
improvement would be real, repeatable and meaningless.

These tests pin the guard, the provenance it depends on, and the fact that the guard can be
switched off — because a design that cannot produce the leaky number cannot demonstrate that
the safe one differs from it.
"""

from __future__ import annotations

import json

import pytest

from codeagent_eval.agent.repo_memory import (
    MAX_INJECTED_NOTES,
    MAX_NOTES,
    MAX_TOTAL_CHARS,
    RepoMemory,
    RepoMemoryError,
)


def store(tmp_path, case_id=None, **over) -> RepoMemory:
    return RepoMemory.load(tmp_path / "memory.json", case_id=case_id, **over)


# --------------------------------------------------------------------------- #
# The contamination guard
# --------------------------------------------------------------------------- #
def test_a_note_written_while_solving_a_case_is_withheld_from_that_same_case(tmp_path):
    """The whole reason this module has a guard.

    Without it, run two of a case reads run one's working notes about that case and scores
    higher for reasons that have nothing to do with memory as a capability.
    """
    first = store(tmp_path, case_id="bugfix-cart-merge")
    first.write({"cart-fix": "the merge bug is in Cart.add_item, compare by sku"})
    first.save()

    again = store(tmp_path, case_id="bugfix-cart-merge")
    assert again.render() == ""
    assert again.readable() == []
    assert again.stats.notes_withheld == 1


def test_the_same_note_is_visible_to_a_different_case(tmp_path):
    """What is left after the guard: knowledge that transferred."""
    first = store(tmp_path, case_id="bugfix-cart-merge")
    first.write({"layout": "library code lives in mini_store/, tests in tests/"})
    first.save()

    other = store(tmp_path, case_id="spec-place-order")
    rendered = other.render()
    assert "library code lives in mini_store/" in rendered
    assert other.stats.notes_withheld == 0
    assert other.stats.notes_read == 1


def test_the_guard_can_be_disabled_so_the_leak_is_measurable(tmp_path):
    """Turning it off is how the safe number is shown to differ from the leaky one."""
    first = store(tmp_path, case_id="bugfix-cart-merge")
    first.write({"cart-fix": "compare by sku in Cart.add_item"})
    first.save()

    leaky = store(tmp_path, case_id="bugfix-cart-merge", exclude_same_case=False)
    assert "compare by sku" in leaky.render()
    assert leaky.stats.notes_withheld == 0


def test_a_note_without_provenance_cannot_be_excluded_and_stays_visible(tmp_path):
    """Provenance is what the guard runs on, so its absence has to be explicit, not silent."""
    (tmp_path / "memory.json").write_text(json.dumps({
        "schema": "algora.repo_memory.v1",
        "notes": [{"key": "k", "value": "v", "case_id": None, "written_at": "2026-01-01"}],
    }))
    loaded = store(tmp_path, case_id="bugfix-cart-merge")
    assert "k: v" in loaded.render()


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_notes_survive_a_reload(tmp_path):
    first = store(tmp_path, case_id="a")
    first.write({"conventions": "money is rounded in exactly one place"})
    first.save()
    assert "money is rounded" in store(tmp_path, case_id="b").render()


def test_a_corrupt_store_starts_empty_rather_than_aborting_a_trial(tmp_path):
    """A half-written file must not make two runs of one configuration diverge."""
    (tmp_path / "memory.json").write_text("{not json")
    loaded = store(tmp_path, case_id="a")
    assert loaded.render() == ""
    loaded.write({"k": "v"})
    loaded.save()
    assert "k: v" in store(tmp_path, case_id="b").render()


def test_a_store_from_an_unknown_schema_is_ignored(tmp_path):
    (tmp_path / "memory.json").write_text(json.dumps({"schema": "other.v9", "notes": [
        {"key": "k", "value": "v", "case_id": None, "written_at": "x"}]}))
    assert store(tmp_path, case_id="a").render() == ""


def test_deletes_and_upserts_apply_as_one_revision(tmp_path):
    memory = store(tmp_path, case_id="a")
    memory.write({"old": "stale", "keep": "good"})
    memory.write({"new": "fresh"}, delete_keys=["old"])
    memory.save()
    # Read from a different case: the guard withholds a session's own notes from itself, so
    # asking the writer what it can see would answer "nothing" for the right reason.
    rendered = store(tmp_path, case_id="b").render()
    assert "new: fresh" in rendered
    assert "keep: good" in rendered
    assert "old" not in rendered
    assert memory.stats.deletes == 1


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #
def test_an_oversized_revision_is_rejected_whole(tmp_path):
    """Partial application would leave a store nobody wrote and nobody can reproduce."""
    memory = store(tmp_path, case_id="a")
    memory.write({"kept": "value"})
    with pytest.raises(RepoMemoryError, match="notes"):
        memory.write({f"k{i}": "v" for i in range(MAX_NOTES + 1)})
    memory.save()
    assert "kept: value" in store(tmp_path, case_id="b").render()


def test_the_total_size_is_capped(tmp_path):
    memory = store(tmp_path, case_id="a")
    with pytest.raises(RepoMemoryError, match="total characters"):
        memory.write({f"k{i}": "x" * 500 for i in range(MAX_TOTAL_CHARS // 400)})


@pytest.mark.parametrize(("key", "value"), [("", "v"), ("k", ""), ("k" * 200, "v"), ("k", "v" * 900)])
def test_malformed_entries_are_refused(tmp_path, key, value):
    with pytest.raises(RepoMemoryError):
        store(tmp_path, case_id="a").write({key: value})


def test_only_a_bounded_number_of_notes_reaches_the_prompt(tmp_path):
    """The store may hold more than is worth reading; the prompt budget is not the store."""
    writer = store(tmp_path, case_id="writer")
    writer.write({f"k{i}": f"fact {i}" for i in range(MAX_INJECTED_NOTES + 5)})
    writer.save()

    reader = store(tmp_path, case_id="reader")
    assert len(reader.readable()) == MAX_INJECTED_NOTES


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #
def test_carried_notes_are_labelled_as_hints_not_instructions(tmp_path):
    """They come from a different task and were never verified for this one."""
    writer = store(tmp_path, case_id="a")
    writer.write({"k": "v"})
    writer.save()
    rendered = store(tmp_path, case_id="b").render()
    assert "not as instructions" in rendered
    assert "earlier, unrelated tasks" in rendered


def test_an_empty_store_renders_nothing_rather_than_an_empty_header(tmp_path):
    assert store(tmp_path, case_id="a").render() == ""
