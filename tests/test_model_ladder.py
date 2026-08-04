"""W1-7: GLM (Zhipu) backend, the model ladder, and cost provenance on a trial.

The ladder exists to restore discrimination on a suite a strong model saturates, so switching
rungs must change exactly one thing — the model — and must be visible afterwards in the run's
provenance rather than hidden in the environment that produced it.
"""

from __future__ import annotations

import dataclasses

import pytest

from codeagent_eval.adapters import BudgetContract, MiniAgentAdapter
from codeagent_eval.llm import LlmProvider, provider_specs
from codeagent_eval.models import AgentTask, LlmCallRecord
from codeagent_eval.settings import Settings


def _settings(**overrides) -> Settings:
    return dataclasses.replace(Settings(), **overrides)


# --------------------------------------------------------------------------- #
# Provider spec table
# --------------------------------------------------------------------------- #
def test_every_backend_declares_its_endpoint_credential_and_models():
    specs = provider_specs(_settings())

    assert set(specs) == {"deepseek", "zhipu", "openai"}
    assert specs["zhipu"].api_key_env == "ZHIPU_API_KEY"
    assert "bigmodel.cn" in specs["zhipu"].base_url
    assert specs["zhipu"].model_for("fast") == "glm-4.7"
    assert specs["openai"].base_url is None  # the SDK default endpoint


def test_zhipu_availability_names_the_missing_credential(monkeypatch):
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    provider = LlmProvider(_settings(llm_provider="zhipu", llm_enable=True))

    assert provider.enabled is False
    assert provider._availability_error() == "ZHIPU_API_KEY is not set."

    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    assert LlmProvider(_settings(llm_provider="zhipu", llm_enable=True)).enabled is True


def test_an_unknown_provider_lists_the_ones_that_exist():
    """A typo in LLM_PROVIDER should be diagnosable without reading the source."""
    provider = LlmProvider(_settings(llm_provider="gpt5", llm_enable=True))
    error = provider._availability_error()

    assert "Unsupported LLM provider: gpt5" in error
    assert "deepseek" in error and "zhipu" in error


def test_endpoint_and_model_stay_consistent_per_backend(monkeypatch):
    """The client, the model name and the availability check all read one spec, so a backend
    cannot be reachable while its provenance reports another backend's model."""
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    provider = LlmProvider(_settings(llm_provider="zhipu", llm_enable=True))

    assert provider.resolved_model("fast") == "glm-4.7"
    assert provider._spec().base_url == provider.settings.zhipu_base_url


# --------------------------------------------------------------------------- #
# The ladder: one flag between rungs
# --------------------------------------------------------------------------- #
def test_model_override_selects_the_rung_and_beats_complexity(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    settings = _settings(llm_provider="zhipu", llm_enable=True)

    default = LlmProvider(settings)
    weak = LlmProvider(settings, model_override="glm-4.7-flash")

    assert default.resolved_model("fast") == "glm-4.7"
    assert weak.resolved_model("fast") == "glm-4.7-flash"
    assert weak.resolved_model("pro") == "glm-4.7-flash", "an explicit rung is not a suggestion"


def test_run_provenance_records_the_rung_and_the_rate_table(monkeypatch):
    from codeagent_eval.runner import _run_config

    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    provider = LlmProvider(
        _settings(llm_provider="zhipu", llm_enable=True), model_override="glm-4.7-flash"
    )
    config = _run_config("v2", provider)

    assert config["provider"] == "zhipu"
    assert config["model"] == "glm-4.7-flash"
    # Without the table's identity, an archived cost figure cannot be checked against the
    # rates that produced it once vendor prices move.
    assert config["pricing_revision"]
    assert "pricing_path" in config


def test_the_deepseek_pro_tier_names_a_model_that_is_actually_pro():
    """Verified live on 2026-08-04: deepseek-reasoner resolves to deepseek-v4-flash, so the
    old default made the "pro" complexity tier a silent no-op that still reported itself as
    a different model in run provenance."""
    specs = provider_specs(_settings())

    assert specs["deepseek"].model_pro == "deepseek-v4-pro"
    assert specs["deepseek"].model_pro != specs["deepseek"].model_fast
    assert "reasoner" not in specs["deepseek"].model_pro


def test_provenance_distinguishes_the_requested_model_from_the_served_one():
    """A provider that silently aliases must not be able to make an artifact claim a model
    that never ran."""
    record = LlmCallRecord(
        provider="deepseek", requested_model="deepseek-reasoner", model="deepseek-v4-flash"
    )

    assert record.requested_model != record.model


# --------------------------------------------------------------------------- #
# Cost on a trial
# --------------------------------------------------------------------------- #
class _ScriptedProvider:
    """Returns one final turn, carrying whatever call records the test wants graded."""

    last_error = None
    settings = None

    def __init__(self, records):
        self._records = records

    def tool_completion(self, **kwargs):  # noqa: ARG002
        from codeagent_eval.llm import _TRACE_BUFFER, LlmToolTurn

        buffer = _TRACE_BUFFER.get()
        if buffer is not None:
            buffer.extend(self._records)
        return LlmToolTurn(content="done", tool_calls=[], finish_reason="stop")


def _record(cost, source="table"):
    return LlmCallRecord(
        provider="zhipu",
        model="glm-4.6",
        prompt_tokens=100,
        completion_tokens=50,
        cached_prompt_tokens=40,
        total_tokens=150,
        estimated_cost_usd=cost,
        cost_source=source,
    )


def _run(records, git_repo):
    from codeagent_eval.sandbox import WorktreeSandbox

    adapter = MiniAgentAdapter(_ScriptedProvider(records), harness="v2")
    task = AgentTask(instruction="x", workspace_path="", max_steps=3, timeout_seconds=30)
    with WorktreeSandbox(git_repo) as sandbox:
        adapter.prepare(sandbox.root, task, BudgetContract(max_wall_clock_s=30), runtime=sandbox)
        result = adapter.run("x")
        adapter.cleanup()
    return result


def test_a_fully_priced_trial_reports_a_derived_cost(git_repo):
    result = _run([_record(0.01), _record(0.02)], git_repo)

    assert result.cost_source == "derived"
    assert result.cost_usd == pytest.approx(0.03)
    assert result.cached_tokens == 80


def test_a_partially_priced_trial_reports_no_cost_at_all(git_repo):
    """Summing only the priced calls would understate the total while still looking like a
    real number, which is worse than reporting nothing."""
    result = _run([_record(0.01), _record(None, source="unavailable")], git_repo)

    assert result.cost_source == "unavailable"
    assert result.cost_usd is None
    # Tokens do not depend on pricing and stay reportable.
    assert result.prompt_tokens == 200


def test_an_unpriced_trial_reports_no_cost(git_repo):
    result = _run([_record(None, source="unavailable")], git_repo)

    assert result.cost_source == "unavailable"
    assert result.cost_usd is None
