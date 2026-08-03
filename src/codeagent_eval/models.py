"""Core data models for CodeAgent Eval Lab.

Two groups:
- Observability records (``LlmCallRecord``) carried over from ft_diag_agent so the
  reused ``llm.py`` / ``observability.py`` work unchanged.
- Coding-domain models (``AgentTask``, ``TraceEvent``) that are new to this project.
  These are intentionally light in M0; M1/M2 extend them as the agent and graders land.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """UTC timestamp in ISO-8601 with a trailing ``Z``, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Observability (reused verbatim from ft_diag_agent's contract)
# --------------------------------------------------------------------------- #
class LlmCallRecord(BaseModel):
    """One sanitized LLM provider call record for observability.

    Prompt bodies and secrets are intentionally not stored; prompt identity is
    a caller-provided version plus a short content fingerprint.
    """

    trace_id: str = Field(default_factory=lambda: f"LLM-{uuid4().hex[:12]}")
    case_id: str | None = None
    node_name: str | None = None
    call_site: str = "unknown"
    call_type: str = "JSON"
    provider: str
    endpoint: str | None = None
    model: str | None = None
    complexity: str = "fast"
    prompt_version: str = "UNVERSIONED"
    prompt_fingerprint: str | None = None
    prompt_chars: int = 0
    message_count: int = 0
    tool_count: int = 0
    max_tokens: int = 0
    status: str = "SUCCESS"
    error: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    created_at: str = Field(default_factory=utc_now_iso)


# --------------------------------------------------------------------------- #
# Coding agent domain
# --------------------------------------------------------------------------- #
class AgentTask(BaseModel):
    """One unit of work handed to the MiniAgent for a single trial."""

    instruction: str
    workspace_path: str
    case_id: str | None = None
    max_steps: int = 20
    timeout_seconds: int = 300
    allowed_tools: list[str] | None = None
    project_instructions: str | None = None  # e.g. injected AGENTS.md content (V2)
    harness_version: str | None = None
    require_tests_run_before_finish: bool = False


class TraceEventType(StrEnum):
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    COMMAND_START = "command_start"
    COMMAND_FINISH = "command_finish"
    TEST_RESULT = "test_result"
    ERROR = "error"
    FINAL_ANSWER = "final_answer"


class TraceEvent(BaseModel):
    """One append-only event in a trial's trajectory (persisted as JSONL)."""

    event_id: str = Field(default_factory=lambda: f"EV-{uuid4().hex[:12]}")
    step: int = 0
    type: TraceEventType
    name: str | None = None  # e.g. tool name, command
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
