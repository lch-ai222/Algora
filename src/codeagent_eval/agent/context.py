"""Context-window management for the MiniAgent: tiered truncation plus compaction.

Two choices here are deliberately conservative, because this code runs inside an evaluation
harness rather than a product:

**Context size is measured, not estimated.** After every turn the provider reports how many
prompt tokens it actually counted, and that number drives compaction. A char/4 heuristic
would drift per model and per tool schema, so the trigger would fire at a different real size
for each system under test — which would make a cross-agent context comparison meaningless.
The heuristic below is used only where nothing has been measured yet.

**Compaction is deterministic, not model-generated.** Summarizing the dropped turns with an
LLM would be smarter, but it injects a nondeterministic, billable call into the middle of
every long trial — so two runs of the same configuration would diverge for reasons unrelated
to the agent being measured. Instead the middle of the conversation is replaced by a digest
built from what actually happened: files read, files written, commands run, tests and their
outcomes. That is both reproducible and the part the agent needs in order to not repeat
itself.

Everything is recorded as a ``COMPACTION`` trace event so a failure that follows a compaction
can be attributed to it rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Rough bytes-per-token used only before the provider has reported a real count.
_CHARS_PER_TOKEN = 4

#: Per-tool output caps, in characters. Reading a file is worth more context than listing a
#: directory, and a failing command's stderr is worth more than its stdout.
DEFAULT_TOOL_OUTPUT_LIMITS: dict[str, int] = {
    "read_file": 6000,
    "search_code": 3000,
    "run_command": 4000,
    "git_diff": 4000,
    "list_files": 2000,
    "apply_patch": 1000,
    "update_plan": 2000,
}
DEFAULT_TOOL_OUTPUT_LIMIT = 3000


@dataclass
class CompactionRecord:
    step: int
    before_tokens: int
    dropped_messages: int
    kept_recent_messages: int
    digest_chars: int


@dataclass
class ContextStats:
    compactions: int = 0
    pressure_notices: int = 0
    truncated_outputs: int = 0
    truncated_chars: int = 0
    peak_prompt_tokens: int = 0
    last_prompt_tokens: int = 0
    records: list[CompactionRecord] = field(default_factory=list)

    def as_dict(self, budget_tokens: int | None) -> dict[str, Any]:
        return {
            "context_budget_tokens": budget_tokens,
            "context_compactions": self.compactions,
            "context_pressure_notices": self.pressure_notices,
            "context_truncated_outputs": self.truncated_outputs,
            "context_truncated_chars": self.truncated_chars,
            "context_peak_prompt_tokens": self.peak_prompt_tokens,
            "context_last_prompt_tokens": self.last_prompt_tokens,
            "context_peak_utilization": (
                round(self.peak_prompt_tokens / budget_tokens, 4)
                if budget_tokens and self.peak_prompt_tokens
                else None
            ),
        }


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Fallback size estimate for the very first turn, before any measurement exists."""
    total = 0
    for message in messages:
        total += len(str(message.get("content") or ""))
        for call in message.get("tool_calls") or ():
            total += len(str(call))
    return total // _CHARS_PER_TOKEN


def truncate(text: str, limit: int) -> tuple[str, int]:
    """Keep the head and tail of an oversized output; both ends carry signal.

    The head names what was inspected and the tail usually holds the error or the result, so
    dropping either loses more than dropping the middle.
    """
    if len(text) <= limit:
        return text, 0
    head = limit // 2
    tail = limit - head
    dropped = len(text) - limit
    return f"{text[:head]}\n…[{dropped} chars elided by context management]…\n{text[-tail:]}", dropped


class ContextManager:
    """Applies output truncation and compaction against a measured token budget."""

    def __init__(
        self,
        budget_tokens: int,
        *,
        compaction_threshold: float = 0.75,
        warn_threshold: float = 0.55,
        keep_recent_messages: int = 6,
        tool_output_limits: dict[str, int] | None = None,
    ) -> None:
        if budget_tokens < 1:
            raise ValueError("budget_tokens must be positive")
        if not 0 < compaction_threshold <= 1:
            raise ValueError("compaction_threshold must be in (0, 1]")
        if not 0 < warn_threshold < compaction_threshold:
            # A warning at or above the compaction point could never fire before the drop,
            # which is the only moment at which it is useful.
            raise ValueError("warn_threshold must be in (0, compaction_threshold)")
        if keep_recent_messages < 2:
            raise ValueError("keep_recent_messages must be at least 2")
        self.budget_tokens = budget_tokens
        self.compaction_threshold = compaction_threshold
        self.warn_threshold = warn_threshold
        self._warned = False
        self.keep_recent_messages = keep_recent_messages
        self.tool_output_limits = tool_output_limits or DEFAULT_TOOL_OUTPUT_LIMITS
        self.stats = ContextStats()

    # -- truncation --------------------------------------------------------- #
    def truncate_tool_output(self, tool_name: str, content: str) -> str:
        limit = self.tool_output_limits.get(tool_name, DEFAULT_TOOL_OUTPUT_LIMIT)
        trimmed, dropped = truncate(content, limit)
        if dropped:
            self.stats.truncated_outputs += 1
            self.stats.truncated_chars += dropped
        return trimmed

    # -- measurement -------------------------------------------------------- #
    def observe(self, prompt_tokens: int | None) -> None:
        """Record the provider's own count of the prompt it just processed."""
        if not prompt_tokens:
            return
        self.stats.last_prompt_tokens = prompt_tokens
        self.stats.peak_prompt_tokens = max(self.stats.peak_prompt_tokens, prompt_tokens)

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        measured = self.stats.last_prompt_tokens or estimate_tokens(messages)
        return measured >= self.budget_tokens * self.compaction_threshold

    def pressure_notice(self, messages: list[dict[str, Any]]) -> str | None:
        """Warn once per approach that context is about to be compacted.

        The ``[context compacted]`` message the digest carries arrives *after* the drop, which
        is too late to act on: anything worth keeping is already gone. Measured, that is what
        happens — with the budget tightened to 8k, compaction fired in 9 of 9 trials, two to
        nine times each, and the scratchpad was written in none of them. The agent had no cue
        that a loss was coming, only that one had happened.

        So the cue is issued while there is still room to record something, and only on the
        rising edge: repeating it every step would spend the very budget it is warning about,
        and re-arming after each compaction keeps it honest for the next approach.
        """
        measured = self.stats.last_prompt_tokens or estimate_tokens(messages)
        if measured < self.budget_tokens * self.warn_threshold:
            self._warned = False
            return None
        if self._warned or self.should_compact(messages):
            return None
        self._warned = True
        self.stats.pressure_notices += 1
        used = round(measured / self.budget_tokens * 100)
        return (
            f"[context pressure] The conversation is at ~{used}% of its context budget and "
            "will be compacted soon; earlier turns will be replaced by a short digest. "
            "Record anything you must not lose — decisions taken, constraints you were given, "
            "what you have already verified — before that happens."
        )

    # -- compaction --------------------------------------------------------- #
    def compact(
        self, messages: list[dict[str, Any]], step: int, digest: str
    ) -> tuple[list[dict[str, Any]], CompactionRecord | None]:
        """Replace the middle of the conversation with a deterministic digest.

        Returns the original list unchanged when there is nothing safe to drop, so a caller
        never has to special-case a short conversation.
        """
        if len(messages) <= self.keep_recent_messages + 1:
            return messages, None

        tail_start = _safe_tail_start(messages, len(messages) - self.keep_recent_messages)
        if tail_start <= 1:
            return messages, None

        head = messages[:1]  # the task statement is never dropped
        tail = messages[tail_start:]
        summary = {
            "role": "user",
            "content": (
                "[context compacted] Earlier turns were removed to stay within the context "
                f"budget. What has happened so far:\n{digest}\n"
                "Continue from here; do not redo work listed above."
            ),
        }
        record = CompactionRecord(
            step=step,
            before_tokens=self.stats.last_prompt_tokens,
            dropped_messages=tail_start - 1,
            kept_recent_messages=len(tail),
            digest_chars=len(digest),
        )
        self.stats.compactions += 1
        self._warned = False  # re-arm for the next approach
        self.stats.records.append(record)
        # The next turn's measurement supersedes this; clearing it prevents an immediate
        # re-trigger on a stale reading.
        self.stats.last_prompt_tokens = 0
        return [*head, summary, *tail], record


def _safe_tail_start(messages: list[dict[str, Any]], target: int) -> int:
    """First index at or after ``target`` where cutting leaves a valid conversation.

    An assistant turn carrying ``tool_calls`` must be followed by a ``tool`` message for each
    call. Cutting between them produces a request the provider rejects, so the boundary is
    advanced until neither side of the cut is orphaned.
    """
    index = max(target, 1)
    while index < len(messages):
        current = messages[index]
        previous = messages[index - 1]
        starts_orphaned_result = current.get("role") == "tool"
        leaves_unanswered_calls = (
            previous.get("role") == "assistant" and bool(previous.get("tool_calls"))
        )
        if not starts_orphaned_result and not leaves_unanswered_calls:
            return index
        index += 1
    return len(messages)
