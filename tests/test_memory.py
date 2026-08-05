"""W2-2 run-scoped ScratchPad: bounds, prompt residency, and isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeagent_eval.adapters import BudgetContract, Capability, MiniAgentAdapter
from codeagent_eval.agent.loop import AgentConfig, MiniAgent, TrialResult
from codeagent_eval.agent.memory import (
    MAX_SCRATCHPAD_NOTES,
    MAX_SCRATCHPAD_VALUE_CHARS,
    ScratchPad,
    ScratchPadError,
)
from codeagent_eval.agent.prompts import build_system_prompt
from codeagent_eval.failure_taxonomy import FailureAttribution
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask, TraceEventType
from codeagent_eval.runner import TRIAL_SCHEMA_VERSION, _aggregate_case, _persist_trial
from codeagent_eval.sandbox import WorktreeSandbox
from codeagent_eval.tools import default_tools


class RecordingProvider:
    last_error = None

    def __init__(self, turns, sizes=None, *, measure_system_chars: bool = False):
        self.turns = list(turns)
        self.sizes = list(sizes or [])
        self.measure_system_chars = measure_system_chars
        self.system_prompts: list[str] = []
        self.last_usage = None

    def tool_completion(self, **kwargs):
        prompt = kwargs["system_prompt"]
        self.system_prompts.append(prompt)
        if self.measure_system_chars:
            self.last_usage = {"prompt_tokens": len(prompt)}
        elif self.sizes:
            self.last_usage = {"prompt_tokens": self.sizes.pop(0)}
        return self.turns.pop(0)


def call(name: str, **arguments) -> LlmToolTurn:
    return LlmToolTurn(
        tool_calls=[LlmToolCall(call_id=f"{name}-{len(arguments)}", name=name, arguments=arguments)]
    )


def memory_call(key: str, value: str) -> LlmToolTurn:
    return call("update_scratchpad", notes=[{"key": key, "value": value}])


def task(*, max_steps: int = 10) -> AgentTask:
    return AgentTask(
        instruction="repair the repository",
        workspace_path="",
        max_steps=max_steps,
        timeout_seconds=60,
    )


def config(**overrides) -> AgentConfig:
    return AgentConfig.for_harness(
        "v3", enforce_completion_checks=False, **overrides
    )


def test_scratchpad_updates_are_bounded_atomic_and_deterministic():
    pad = ScratchPad()
    pad.update({"z-decision": "keep API", "a-constraint": "do not edit tests"})
    before = pad.snapshot()

    with pytest.raises(ScratchPadError, match="value exceeds"):
        pad.update({"oversized": "x" * (MAX_SCRATCHPAD_VALUE_CHARS + 1)})

    assert pad.snapshot() == before, "an invalid revision must not partially mutate memory"
    assert pad.render().index("a-constraint") < pad.render().index("z-decision")
    pad.update(delete_keys=["z-decision"])
    assert pad.notes == {"a-constraint": "do not edit tests"}


def test_scratchpad_rejects_capacity_and_ambiguous_revisions():
    pad = ScratchPad()
    with pytest.raises(ScratchPadError, match="exceeds .* notes"):
        pad.update({f"k{index}": "v" for index in range(MAX_SCRATCHPAD_NOTES + 1)})
    with pytest.raises(ScratchPadError, match="upsert and delete"):
        pad.update({"decision": "new"}, delete_keys=["decision"])
    assert pad.notes == {}


def test_only_v3_gets_working_memory_and_it_is_independently_ablatable():
    assert "update_scratchpad" not in [tool.name for tool in default_tools()]
    assert "update_scratchpad" in [tool.name for tool in default_tools(memory=True)]
    assert AgentConfig.for_harness("v2").enable_scratchpad is False
    assert AgentConfig.for_harness("v3").enable_scratchpad is True
    assert AgentConfig.for_harness(
        "v3", ablate=frozenset({"scratchpad"})
    ).enable_scratchpad is False
    assert Capability.WORKING_MEMORY in MiniAgentAdapter(None, harness="v3").capabilities()
    assert Capability.MEMORY not in MiniAgentAdapter(None, harness="v3").capabilities()
    assert "update_scratchpad" in build_system_prompt("v3")
    assert "update_scratchpad" not in build_system_prompt("v3", scratchpad=False)


def test_memory_survives_compaction_without_becoming_a_repo_patch(git_repo: Path):
    durable = "cart merge must preserve positive quantity validation"
    provider = RecordingProvider(
        [
            memory_call("constraint", durable),
            call("read_file", path="app.py", start=1),
            call("read_file", path="app.py", start=2),
            call("read_file", path="app.py", start=3),
            LlmToolTurn(content="done", tool_calls=[]),
        ],
        [100, 100, 100, 900, 100],
    )
    with WorktreeSandbox(git_repo) as sandbox:
        trial = MiniAgent(
            provider,
            config(context_budget_tokens=1_000, compaction_threshold=0.75),
        ).run(task(), sandbox)

    assert any(event.type == TraceEventType.COMPACTION for event in trial.events)
    assert durable in provider.system_prompts[-1]
    assert trial.memory["notes"] == [{"key": "constraint", "value": durable}]
    assert trial.completion_checks["scratchpad_revisions"] == 1
    assert trial.patch == "" and trial.changed_files == []
    update_events = [event for event in trial.events if event.type == TraceEventType.MEMORY_UPDATE]
    assert update_events[0].payload["updated_keys"] == ["constraint"]
    assert durable not in "\n".join(event.model_dump_json() for event in trial.events)


def test_memory_survives_a_user_followup_in_the_same_session(git_repo: Path):
    durable = "the public signature cannot change"
    provider = RecordingProvider([
        memory_call("api", durable),
        LlmToolTurn(content="first final", tool_calls=[]),
        LlmToolTurn(content="follow-up final", tool_calls=[]),
    ])
    agent = MiniAgent(provider, config(enable_context_management=False))

    with WorktreeSandbox(git_repo) as sandbox:
        first = agent.run(task(), sandbox)
        final = agent.continue_("Also cover the custom-rate path.")

    assert first.stop_reason == final.stop_reason == "final"
    assert durable in provider.system_prompts[1]
    assert durable in provider.system_prompts[2]
    assert final.memory == first.memory


def test_a_new_trial_gets_a_fresh_scratchpad_even_when_the_agent_object_is_reused(
    git_repo: Path,
):
    durable = "must not leak into another repeat"
    provider = RecordingProvider([
        memory_call("private", durable),
        LlmToolTurn(content="first", tool_calls=[]),
        LlmToolTurn(content="second", tool_calls=[]),
    ])
    agent = MiniAgent(provider, config(enable_context_management=False))

    with WorktreeSandbox(git_repo) as sandbox:
        first = agent.run(task(), sandbox)
        second = agent.run(task(max_steps=2), sandbox)

    assert first.memory["notes"]
    assert second.memory["notes"] == []
    assert durable not in provider.system_prompts[2]


def test_scratchpad_text_counts_toward_the_measured_context_ceiling(git_repo: Path):
    value = "x" * MAX_SCRATCHPAD_VALUE_CHARS
    provider = RecordingProvider(
        [memory_call("large-fact", value), LlmToolTurn(content="unreachable", tool_calls=[])],
        measure_system_chars=True,
    )
    ceiling = len(build_system_prompt("v3")) + 500

    with WorktreeSandbox(git_repo) as sandbox:
        trial = MiniAgent(
            provider,
            config(enable_context_management=False, context_ceiling_tokens=ceiling),
        ).run(task(), sandbox)

    assert trial.stop_reason == "context_overflow"
    assert trial.completion_checks["peak_prompt_tokens"] > ceiling
    assert value in provider.system_prompts[-1]


def test_memory_artifact_schema_and_case_aggregation_are_auditable(tmp_path: Path):
    pad = ScratchPad()
    pad.note("decision", "keep API")
    memory = pad.snapshot()
    checks = pad.stats.as_dict(pad.notes)
    trial = TrialResult(stop_reason="final", memory=memory, completion_checks=checks)
    grade = GradeResult.model_construct(case_id="c", task_success=True, strict_success=True)
    attribution = FailureAttribution(case_id="c", failed=False)
    trial_dir = tmp_path / "trial"

    _persist_trial(trial_dir, {"case_id": "c"}, trial, grade, attribution)
    summary = _aggregate_case("c", [grade], [trial], [attribution])

    assert json.loads((trial_dir / "scratchpad.json").read_text()) == memory
    assert json.loads((trial_dir / "trial-complete.json").read_text())["schema_version"] == (
        TRIAL_SCHEMA_VERSION
    )
    assert summary["scratchpad_trials"] == 1
    assert summary["scratchpad_usage_rate"] == 1.0
    assert summary["scratchpad_revisions_mean"] == 1.0
    assert summary["scratchpad_final_notes_mean"] == 1.0


def test_scratchpad_ablation_is_recorded_in_adapter_identity_and_manifest(git_repo: Path):
    provider = RecordingProvider([LlmToolTurn(content="done", tool_calls=[])])
    adapter = MiniAgentAdapter(
        provider,
        harness="v3",
        ablate=frozenset({"scratchpad"}),
    )
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(
            sandbox.root,
            task(max_steps=2),
            BudgetContract(max_wall_clock_s=30),
            runtime=sandbox,
        )
        result = adapter.run("finish")
        adapter.cleanup()

    assert adapter.adapter_version.endswith("+v3.3-no_scratchpad")
    assert result.env_manifest["ablate"] == ["scratchpad"]
    assert result.memory == {}
    assert "scratchpad_used" not in result.completion_checks
    assert "update_scratchpad" not in provider.system_prompts[0]
