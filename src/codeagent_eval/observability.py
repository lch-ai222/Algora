"""Dependency-free local exporter for sanitized LLM call telemetry.

Copied near-verbatim from ft_diag_agent: writes JSONL only so trial execution never
depends on a network collector. External systems (OTel, Langfuse) can ingest the file
later; the row shape is selectable via ``LLM_OBSERVABILITY_EXPORTER``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from codeagent_eval.models import LlmCallRecord, utc_now_iso
from codeagent_eval.settings import Settings

LlmExporterMode = Literal["local_jsonl", "otel_jsonl", "langfuse_jsonl"]
_DISABLED_MODES = {"", "none", "off", "disabled", "false", "0"}
_SUPPORTED_MODES = {"local_jsonl", "otel_jsonl", "langfuse_jsonl"}


class LocalLlmObservabilityExporter:
    def __init__(self, path: str | Path, mode: LlmExporterMode = "local_jsonl"):
        self.path = Path(path)
        self.mode = mode

    def export_llm_calls(self, calls: list[LlmCallRecord]) -> Path | None:
        if not calls:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for call in calls:
                handle.write(json.dumps(self._row(call), ensure_ascii=False) + "\n")
        return self.path

    def _row(self, call: LlmCallRecord) -> dict[str, Any]:
        if self.mode == "otel_jsonl":
            return _otel_span_row(call)
        if self.mode == "langfuse_jsonl":
            return _langfuse_generation_row(call)
        return _local_call_row(call)


def build_llm_observability_exporter(settings: Settings) -> LocalLlmObservabilityExporter | None:
    mode = settings.llm_observability_exporter.strip().lower()
    if mode in _DISABLED_MODES or mode not in _SUPPORTED_MODES:
        return None
    return LocalLlmObservabilityExporter(
        path=_resolve_observability_export_path(settings),
        mode=mode,  # type: ignore[arg-type]
    )


def _resolve_observability_export_path(settings: Settings) -> Path:
    path = settings.llm_observability_export_path
    return path if path.is_absolute() else settings.runs_dir / path


def _local_call_row(call: LlmCallRecord) -> dict[str, Any]:
    return {
        "schema": "codeagent_eval.llm_call.v1",
        "exported_at": utc_now_iso(),
        **call.model_dump(),
    }


def _otel_span_row(call: LlmCallRecord) -> dict[str, Any]:
    return {
        "schema": "otel.span.v1",
        "name": f"llm.{call.call_type.lower()}",
        "trace_id": call.trace_id,
        "span_id": call.trace_id[-16:],
        "start_time": call.created_at,
        "duration_ms": call.latency_ms,
        "status": {
            "code": "OK" if call.status == "SUCCESS" else ("UNSET" if call.status == "SKIPPED" else "ERROR"),
            "message": call.error,
        },
        "attributes": {
            "case_id": call.case_id,
            "node_name": call.node_name,
            "llm.call_site": call.call_site,
            "llm.call_type": call.call_type,
            "llm.provider": call.provider,
            "llm.model": call.model,
            "llm.prompt_tokens": call.prompt_tokens,
            "llm.completion_tokens": call.completion_tokens,
            "llm.total_tokens": call.total_tokens,
            "llm.estimated_cost_usd": call.estimated_cost_usd,
        },
        "exported_at": utc_now_iso(),
    }


def _langfuse_generation_row(call: LlmCallRecord) -> dict[str, Any]:
    return {
        "schema": "langfuse.generation.v1",
        "id": call.trace_id,
        "traceId": call.case_id or call.trace_id,
        "name": call.call_site,
        "startTime": call.created_at,
        "model": call.model,
        "usage": {
            "input": call.prompt_tokens,
            "output": call.completion_tokens,
            "total": call.total_tokens,
        },
        "metadata": {
            "node_name": call.node_name,
            "call_type": call.call_type,
            "provider": call.provider,
            "status": call.status,
            "error": call.error,
            "latency_ms": call.latency_ms,
            "estimated_cost_usd": call.estimated_cost_usd,
        },
        "exported_at": utc_now_iso(),
    }
