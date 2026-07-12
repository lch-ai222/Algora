"""M0 acceptance: the reused LLM provider parses structured tool_calls and records
LlmCallRecords into an active trace scope — verified offline with a fake OpenAI client
so no API key is required in CI."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from codeagent_eval.llm import LlmProvider, llm_trace_scope
from codeagent_eval.settings import Settings


def _settings(**overrides) -> Settings:
    base = Settings()
    return dataclasses.replace(base, **overrides)


class _FakeCompletions:
    def __init__(self, message):
        self._message = message

    def create(self, **kwargs):  # noqa: ARG002 - mimics openai signature
        return SimpleNamespace(
            choices=[SimpleNamespace(message=self._message)],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )


class _FakeClient:
    def __init__(self, message):
        self.chat = SimpleNamespace(completions=_FakeCompletions(message))


def _fake_tool_message():
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="read_file", arguments='{"path": "app/store.py", "start": 1}'),
    )
    return SimpleNamespace(content=None, tool_calls=[tool_call])


def test_tool_completion_parses_structured_tool_calls(monkeypatch):
    settings = _settings(llm_provider="deepseek", llm_enable=True)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = LlmProvider(settings)
    monkeypatch.setattr(
        provider, "_client_and_model", lambda complexity: (_FakeClient(_fake_tool_message()), "fake-model")
    )

    with llm_trace_scope(case_id="case-1", node_name="agent_loop") as records:
        turn = provider.tool_completion(
            system_prompt="you are a coding agent",
            messages=[{"role": "user", "content": "fix the bug"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
        )

    assert turn is not None
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert call.name == "read_file"
    assert call.arguments == {"path": "app/store.py", "start": 1}
    assert call.arguments_error is None

    # trace scope captured exactly one successful, token-accounted record
    assert len(records) == 1
    assert records[0].status == "SUCCESS"
    assert records[0].case_id == "case-1"
    assert records[0].total_tokens == 18
    assert records[0].tool_count == 1


def test_tool_completion_reports_bad_arguments(monkeypatch):
    settings = _settings(llm_provider="deepseek", llm_enable=True)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = LlmProvider(settings)
    bad = SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(name="run_command", arguments="{not json"))],
    )
    monkeypatch.setattr(provider, "_client_and_model", lambda complexity: (_FakeClient(bad), "fake-model"))

    turn = provider.tool_completion(system_prompt="s", messages=[], tools=[])
    assert turn is not None
    assert turn.tool_calls[0].arguments_error is not None


def test_disabled_provider_degrades_and_records_skip():
    provider = LlmProvider(_settings(llm_enable=False))
    with llm_trace_scope(case_id="case-x") as records:
        turn = provider.tool_completion(system_prompt="s", messages=[], tools=[])
    assert turn is None
    assert provider.last_error is not None
    assert len(records) == 1
    assert records[0].status == "SKIPPED"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
