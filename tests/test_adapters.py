"""W1-2: normalized adapter contracts preserve MiniAgent behavior and provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeagent_eval.adapters import (
    AgentAdapter,
    BudgetContract,
    MiniAgentAdapter,
    UnsupportedCapability,
    create_adapter,
)
from codeagent_eval.agent.loop import TrialResult
from codeagent_eval.benchmark import EvalCase
from codeagent_eval.failure_taxonomy import FailureAttribution
from codeagent_eval.graders.result import GradeResult
from codeagent_eval.llm import LlmToolCall, LlmToolTurn
from codeagent_eval.models import AgentTask
from codeagent_eval.runner import (
    _aggregate_case,
    _experiment_exit_code,
    _resolve_agent_kind,
    _run_adapter_trial,
)
from codeagent_eval.sandbox import WorktreeSandbox


class ScriptedProvider:
    last_error = None

    def __init__(self) -> None:
        self._turns = [
            LlmToolTurn(
                tool_calls=[
                    LlmToolCall(
                        call_id="edit",
                        name="apply_patch",
                        arguments={
                            "path": "app.py",
                            "old_str": "return a - b  # bug: should be +",
                            "new_str": "return a + b",
                        },
                    )
                ]
            ),
            LlmToolTurn(
                tool_calls=[
                    LlmToolCall(call_id="test", name="run_command", arguments={"command": "pytest -q"})
                ]
            ),
            LlmToolTurn(content="done", tool_calls=[]),
        ]

    def tool_completion(self, **kwargs):  # noqa: ARG002
        return self._turns.pop(0)


def test_budget_contract_rejects_invalid_limits():
    with pytest.raises(ValueError):
        BudgetContract(max_wall_clock_s=0)
    with pytest.raises(ValueError):
        BudgetContract(max_wall_clock_s=10, max_cost_usd=0)


def test_registry_returns_protocol_compatible_adapter():
    adapter = create_adapter(
        "mini_agent",
        provider=ScriptedProvider(),
        harness="v2",
        max_completion_tokens=4096,
    )
    assert isinstance(adapter, AgentAdapter)
    assert adapter.probe().available is True
    assert adapter.capabilities() == set()
    assert adapter.max_completion_tokens == 4096
    with pytest.raises(ValueError, match="unknown adapter"):
        create_adapter("missing", provider=None)


def test_mini_adapter_normalizes_and_round_trips_trial(git_repo: Path):
    case = EvalCase(case_id="adapter-case", task_type="bugfix", instruction="fix add")
    task = AgentTask(
        instruction=case.instruction,
        workspace_path="",
        case_id=case.case_id,
        harness_version="v2",
        max_steps=10,
        timeout_seconds=60,
    )
    with WorktreeSandbox(git_repo) as sandbox:
        trial, normalized = _run_adapter_trial(task, sandbox, case, ScriptedProvider())

    assert normalized.adapter == "mini_agent"
    assert normalized.adapter_version.endswith("+v2")
    assert normalized.stop_reason == "final"
    assert normalized.native_stop_reason == "final"
    assert normalized.budget.max_steps == case.max_steps
    assert normalized.env_manifest["repo_commit"]
    assert normalized.cost_source == "unavailable"
    assert normalized.cost_usd is None
    assert "+    return a + b" in normalized.patch
    assert trial.model_dump() == normalized.to_trial_result().model_dump()
    assert '"adapter":"mini_agent"' in normalized.model_dump_json()


def test_mini_adapter_rejects_unenforceable_budget(git_repo: Path):
    adapter = MiniAgentAdapter(ScriptedProvider(), harness="v1")
    task = AgentTask(instruction="x", workspace_path="", max_steps=2, timeout_seconds=10)
    with WorktreeSandbox(git_repo) as sandbox:
        with pytest.raises(UnsupportedCapability, match="cost budget"):
            adapter.prepare(
                sandbox.root,
                task,
                BudgetContract(max_wall_clock_s=10, max_cost_usd=1.0),
                runtime=sandbox,
            )


def test_cli_selection_preserves_legacy_default_and_adapter_v2_default():
    assert _resolve_agent_kind(None, None, "v2") == "v1"
    assert _resolve_agent_kind("reference", None, "v2") == "reference"
    assert _resolve_agent_kind(None, "mini_agent", "v2") == "v2"
    with pytest.raises(ValueError, match="mutually exclusive"):
        _resolve_agent_kind("v1", "mini_agent", "v2")


def test_provider_failure_is_infra_invalid_not_zero_capability():
    grade = GradeResult.model_construct(task_success=False, strict_success=False)
    trial = TrialResult(
        stop_reason="provider_error",
        completion_checks={"provider_error": True},
    )
    attribution = FailureAttribution(case_id="c", failed=True, primary="ENVIRONMENT")
    aggregate = _aggregate_case("c", [grade], [trial], [attribution])

    assert aggregate["valid_trials"] == 0
    assert aggregate["infra_failures"] == 1
    assert aggregate["task_success_rate"] is None
    assert aggregate["pass_at_k"] is None
    assert _experiment_exit_code({"infra_failures": 1}) == 3
