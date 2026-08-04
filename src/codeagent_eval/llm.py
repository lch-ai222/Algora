"""OpenAI-compatible LLM provider with tool-calling, structured JSON, and call tracing.

Adapted from ft_diag_agent's ``llm.py``: the fault-tree domain imports are dropped,
but the provider contract is unchanged so the MiniAgent loop and the LLM-Judge share
one battle-tested tool-calling path. DeepSeek, Zhipu (GLM) and OpenAI are all
OpenAI-compatible; ``LLM_PROVIDER`` selects which, and ``ProviderSpec`` keeps the
endpoint/model/credential facts of each one in a single place.

The agentic multi-turn loop lives in ``agent/loop.py`` — this module exposes one
tool turn (``tool_completion``) and one structured-JSON call (``json_completion``).
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from codeagent_eval.models import LlmCallRecord
from codeagent_eval.pricing import cached_price_table
from codeagent_eval.settings import Settings

T = TypeVar("T", bound=BaseModel)
_TRACE_CONTEXT: ContextVar[dict[str, str | None] | None] = ContextVar("llm_trace_context", default=None)
_TRACE_BUFFER: ContextVar[list[LlmCallRecord] | None] = ContextVar("llm_trace_buffer", default=None)


@contextmanager
def llm_trace_scope(case_id: str | None = None, node_name: str | None = None):
    """Collect LLM calls made inside one logical unit (e.g. a trial) without globals."""
    records: list[LlmCallRecord] = []
    ctx_token = _TRACE_CONTEXT.set({"case_id": case_id, "node_name": node_name})
    buffer_token = _TRACE_BUFFER.set(records)
    try:
        yield records
    finally:
        _TRACE_BUFFER.reset(buffer_token)
        _TRACE_CONTEXT.reset(ctx_token)


class LlmToolCall(BaseModel):
    """One function call requested by the model in a tool-use turn."""

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    arguments_error: str | None = None


class LlmToolTurn(BaseModel):
    """One assistant turn from a tool-enabled chat completion."""

    content: str | None = None
    tool_calls: list[LlmToolCall] = Field(default_factory=list)
    finish_reason: str | None = None


@dataclass(frozen=True)
class ProviderSpec:
    """One OpenAI-compatible backend: where to reach it and which models it exposes.

    Kept as data rather than three parallel if-chains (client, model, availability) so adding
    a backend cannot leave one of them behind — which is exactly how a run ends up reporting
    the wrong model name in its provenance.
    """

    name: str
    api_key_env: str
    base_url: str | None
    model_fast: str
    model_pro: str

    def model_for(self, complexity: str) -> str:
        return self.model_pro if complexity == "pro" else self.model_fast


def provider_specs(settings: Settings) -> dict[str, ProviderSpec]:
    return {
        "deepseek": ProviderSpec(
            name="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url=settings.deepseek_base_url,
            model_fast=settings.deepseek_model_fast,
            model_pro=settings.deepseek_model_pro,
        ),
        "zhipu": ProviderSpec(
            name="zhipu",
            api_key_env="ZHIPU_API_KEY",
            base_url=settings.zhipu_base_url,
            model_fast=settings.zhipu_model_fast,
            model_pro=settings.zhipu_model_pro,
        ),
        "openai": ProviderSpec(
            name="openai",
            api_key_env="OPENAI_API_KEY",
            base_url=None,
            model_fast=settings.openai_model,
            model_pro=settings.openai_model,
        ),
    }


class LlmProvider:
    def __init__(self, settings: Settings, *, model_override: str | None = None):
        self.settings = settings
        # Set by --model so one ladder rung differs from another by exactly one flag, with the
        # override still visible in run provenance rather than hidden in the environment.
        self.model_override = model_override
        self._specs = provider_specs(settings)
        self._price_table = cached_price_table(str(settings.pricing_path))
        self.last_error: str | None = None
        self.last_model: str | None = None
        self.last_raw_content: str | None = None
        self.last_usage: dict[str, int] | None = None
        self.last_call: LlmCallRecord | None = None
        self.call_history: list[LlmCallRecord] = []
        # One HTTP client per provider endpoint; the SDK client carries timeout +
        # retries with backoff for transient errors (connection failures, 429, 5xx).
        self._clients: dict[tuple[str, str | None], Any] = {}

    def _spec(self) -> ProviderSpec:
        spec = self._specs.get(self.settings.llm_provider)
        if spec is None:
            raise ValueError(f"Unsupported LLM provider: {self.settings.llm_provider}")
        return spec

    def _get_client(self) -> Any:
        from openai import OpenAI

        spec = self._spec()
        cache_key: tuple[str, str | None] = (spec.name, spec.base_url)
        api_key = os.environ[spec.api_key_env]
        base_url = spec.base_url
        client = self._clients.get(cache_key)
        if client is None:
            client_kwargs: dict[str, Any] = {
                "api_key": api_key,
                "timeout": self.settings.llm_timeout_seconds,
                "max_retries": self.settings.llm_max_retries,
            }
            if base_url:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)
            self._clients[cache_key] = client
        return client

    @property
    def enabled(self) -> bool:
        return self._availability_error() is None

    def resolved_model(self, complexity: str = "fast") -> str | None:
        """Public model name for the current provider + complexity (for run provenance)."""
        if self.model_override:
            return self.model_override
        return self._expected_model(complexity)

    def tool_completion(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        complexity: str = "fast",
        max_tokens: int = 2048,
        temperature: float | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        call_site: str = "llm.tool_completion",
        prompt_version: str = "UNVERSIONED",
    ) -> LlmToolTurn | None:
        """Run one tool-enabled chat turn. ``messages`` use OpenAI chat format and may
        include prior assistant tool_calls and role="tool" results. Returns ``None`` on
        unavailability or call failure with the reason in ``last_error`` — callers (the
        agent loop) treat that as a degradation signal, they must not raise into a trial."""
        started = perf_counter()
        self.last_error = None
        self.last_raw_content = None
        self.last_usage = None
        self.last_call = None
        self.last_model = None
        status = "ERROR"
        availability_error = self._availability_error()
        if availability_error:
            self.last_error = availability_error
            self._record_call(
                call_type="TOOL",
                call_site=call_site,
                complexity=complexity,
                prompt_version=prompt_version,
                prompt_fingerprint=_prompt_fingerprint(system_prompt, json.dumps(messages, ensure_ascii=False)),
                prompt_chars=len(system_prompt) + len(json.dumps(messages, ensure_ascii=False)),
                message_count=len(messages) + 1,
                tool_count=len(tools),
                max_tokens=max_tokens,
                status="SKIPPED",
                started=started,
            )
            return None
        try:
            client, model = self._client_and_model(complexity)
            self.last_model = model
            kwargs: dict[str, Any] = {}
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
            if temperature is not None:
                kwargs["temperature"] = temperature
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, *messages],
                tools=tools,
                max_tokens=max_tokens,
                **kwargs,
            )
            self.last_usage = _usage_dict(response)
            choice = response.choices[0]
            message = choice.message
            self.last_raw_content = message.content
            tool_calls: list[LlmToolCall] = []
            for raw_call in message.tool_calls or []:
                arguments: dict[str, Any] = {}
                arguments_error: str | None = None
                try:
                    parsed = json.loads(raw_call.function.arguments or "{}")
                    if isinstance(parsed, dict):
                        arguments = parsed
                    else:
                        arguments_error = f"tool arguments are not a JSON object: {type(parsed).__name__}"
                except json.JSONDecodeError as exc:
                    arguments_error = f"tool arguments JSON parse failed: {_compact_error(str(exc), 200)}"
                tool_calls.append(
                    LlmToolCall(
                        call_id=raw_call.id,
                        name=raw_call.function.name,
                        arguments=arguments,
                        arguments_error=arguments_error,
                    )
                )
            status = "SUCCESS"
            return LlmToolTurn(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason=getattr(choice, "finish_reason", None),
            )
        except Exception as exc:
            self.last_error = f"LLM tool call failed: {_compact_error(_exception_label(exc))}"
            return None
        finally:
            if self.last_call is None:
                messages_text = json.dumps(messages, ensure_ascii=False)
                self._record_call(
                    call_type="TOOL",
                    call_site=call_site,
                    complexity=complexity,
                    prompt_version=prompt_version,
                    prompt_fingerprint=_prompt_fingerprint(system_prompt, messages_text),
                    prompt_chars=len(system_prompt) + len(messages_text),
                    message_count=len(messages) + 1,
                    tool_count=len(tools),
                    max_tokens=max_tokens,
                    status=status,
                    started=started,
                )

    def json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        complexity: str = "fast",
        max_tokens: int = 1200,
        temperature: float | None = None,
        call_site: str = "llm.json_completion",
        prompt_version: str = "UNVERSIONED",
    ) -> T | None:
        """Structured-JSON call validated into ``response_model``. Used by the LLM-Judge
        (M5); returns ``None`` on failure with the reason in ``last_error``."""
        started = perf_counter()
        self.last_error = None
        self.last_raw_content = None
        self.last_usage = None
        self.last_call = None
        self.last_model = None
        status = "ERROR"
        availability_error = self._availability_error()
        if availability_error:
            self.last_error = availability_error
            self._record_call(
                call_type="JSON",
                call_site=call_site,
                complexity=complexity,
                prompt_version=prompt_version,
                prompt_fingerprint=_prompt_fingerprint(system_prompt, user_prompt),
                prompt_chars=len(system_prompt) + len(user_prompt),
                message_count=2,
                tool_count=0,
                max_tokens=max_tokens,
                status="SKIPPED",
                started=started,
            )
            return None
        try:
            client, model = self._client_and_model(complexity)
            self.last_model = model
            kwargs: dict[str, Any] = {}
            if temperature is not None:
                kwargs["temperature"] = temperature
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"{system_prompt}\nOutput valid JSON only."},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                **kwargs,
            )
            content = response.choices[0].message.content or "{}"
            self.last_raw_content = content
            self.last_usage = _usage_dict(response)
            validated = response_model.model_validate(json.loads(content))
            status = "SUCCESS"
            return validated
        except ValidationError as exc:
            self.last_error = f"LLM JSON schema validation failed: {_compact_error(str(exc))}"
            return None
        except Exception as exc:
            self.last_error = f"LLM call failed: {_compact_error(_exception_label(exc))}"
            return None
        finally:
            if self.last_call is None:
                self._record_call(
                    call_type="JSON",
                    call_site=call_site,
                    complexity=complexity,
                    prompt_version=prompt_version,
                    prompt_fingerprint=_prompt_fingerprint(system_prompt, user_prompt),
                    prompt_chars=len(system_prompt) + len(user_prompt),
                    message_count=2,
                    tool_count=0,
                    max_tokens=max_tokens,
                    status=status,
                    started=started,
                )

    def _client_and_model(self, complexity: str):
        return self._get_client(), self.model_override or self._spec().model_for(complexity)

    def _availability_error(self) -> str | None:
        if not self.settings.llm_enable:
            return "LLM_ENABLE is false; LLM calls are disabled."
        spec = self._specs.get(self.settings.llm_provider)
        if spec is None:
            return (
                f"Unsupported LLM provider: {self.settings.llm_provider} "
                f"(known: {', '.join(sorted(self._specs))})"
            )
        if not os.getenv(spec.api_key_env):
            return f"{spec.api_key_env} is not set."
        return None

    def pricing_provenance(self) -> dict[str, Any]:
        """Which rate table backed this run's cost figures."""
        return self._price_table.provenance()

    def _record_call(
        self,
        *,
        call_type: str,
        call_site: str,
        complexity: str,
        prompt_version: str,
        prompt_fingerprint: str | None,
        prompt_chars: int,
        message_count: int,
        tool_count: int,
        max_tokens: int,
        status: str,
        started: float,
    ) -> LlmCallRecord:
        usage = self.last_usage or {}
        context = _TRACE_CONTEXT.get() or {}
        model = self.last_model or self._expected_model(complexity)
        estimate = self._price_table.estimate(
            provider=self.settings.llm_provider,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_prompt_tokens=int(usage.get("cached_prompt_tokens") or 0),
        )
        record = LlmCallRecord(
            case_id=context.get("case_id"),
            node_name=context.get("node_name"),
            call_site=call_site,
            call_type=call_type,
            provider=self.settings.llm_provider,
            endpoint=self._endpoint_label(),
            model=model,
            complexity=complexity,
            prompt_version=prompt_version,
            prompt_fingerprint=prompt_fingerprint,
            prompt_chars=prompt_chars,
            message_count=message_count,
            tool_count=tool_count,
            max_tokens=max_tokens,
            status=status,
            error=self.last_error,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_prompt_tokens=int(usage.get("cached_prompt_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            estimated_cost_usd=estimate.amount_usd,
            cost_source=estimate.source,
            cost_note=estimate.reason,
        )
        self.last_call = record
        self.call_history.append(record)
        buffer = _TRACE_BUFFER.get()
        if buffer is not None:
            buffer.append(record)
        return record

    def _expected_model(self, complexity: str) -> str | None:
        spec = self._specs.get(self.settings.llm_provider)
        return spec.model_for(complexity) if spec else None

    def _endpoint_label(self) -> str | None:
        spec = self._specs.get(self.settings.llm_provider)
        return spec.base_url if spec else None


def _usage_dict(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cached_prompt_tokens": _cached_prompt_tokens(usage),
    }


def _cached_prompt_tokens(usage: Any) -> int:
    """Prompt-cache hits, which most vendors bill at a reduced rate.

    Two shapes are in circulation: DeepSeek's flat ``prompt_cache_hit_tokens`` and the
    OpenAI-compatible ``prompt_tokens_details.cached_tokens`` that Zhipu and OpenAI use.
    Reading only one of them would understate cache usage and overstate cost for the other.
    """
    flat = getattr(usage, "prompt_cache_hit_tokens", None)
    if flat is not None:
        return max(0, int(flat or 0))
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        return 0
    cached = (
        details.get("cached_tokens") if isinstance(details, dict)
        else getattr(details, "cached_tokens", None)
    )
    return max(0, int(cached or 0))


def _prompt_fingerprint(system_prompt: str, user_prompt: str) -> str:
    digest = sha256(f"{system_prompt}\n---\n{user_prompt}".encode()).hexdigest()
    return digest[:24]


def _exception_label(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _compact_error(value: str, limit: int = 500) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
