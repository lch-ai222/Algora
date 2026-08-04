"""Runtime settings for CodeAgent Eval Lab.

Adapted from ft_diag_agent's settings pattern, trimmed to what the coding agent
and evaluation pipeline need (LLM provider + paths + observability). Env-driven,
frozen dataclass so a run's configuration is a plain snapshot we can archive.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> Path:
    return field(default_factory=lambda: Path(os.getenv(name, default)))


def _str_env(name: str, default: str):
    return field(default_factory=lambda: os.getenv(name, default))


def _int_env(name: str, default: str):
    return field(default_factory=lambda: int(os.getenv(name, default)))


def _float_env(name: str, default: str):
    return field(default_factory=lambda: float(os.getenv(name, default)))


@dataclass(frozen=True)
class Settings:
    # --- LLM provider (OpenAI-compatible) ---
    llm_provider: str = _str_env("LLM_PROVIDER", "deepseek")
    llm_enable: bool = field(default_factory=lambda: _bool_env("LLM_ENABLE", False))
    llm_timeout_seconds: float = _float_env("LLM_TIMEOUT_SECONDS", "60")
    llm_max_retries: int = _int_env("LLM_MAX_RETRIES", "2")
    # Cost comes from the per-model table in config/pricing.json, not from a flat rate:
    # a model ladder prices each rung differently, and a single global number would be
    # silently wrong for every rung but one.
    pricing_path: Path = _path_env("PRICING_PATH", "config/pricing.json")

    deepseek_base_url: str = _str_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model_fast: str = _str_env("DEEPSEEK_MODEL_FAST", "deepseek-chat")
    deepseek_model_pro: str = _str_env("DEEPSEEK_MODEL_PRO", "deepseek-reasoner")
    zhipu_base_url: str = _str_env("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    zhipu_model_fast: str = _str_env("ZHIPU_MODEL_FAST", "glm-4.6")
    zhipu_model_pro: str = _str_env("ZHIPU_MODEL_PRO", "glm-4.6")
    openai_model: str = _str_env("OPENAI_MODEL", "gpt-5.4-mini")

    # --- Observability ---
    llm_observability_exporter: str = _str_env("LLM_OBSERVABILITY_EXPORTER", "none")
    llm_observability_export_path: Path = _path_env(
        "LLM_OBSERVABILITY_EXPORT_PATH", "llm_observability.jsonl"
    )

    # --- Paths ---
    artifacts_dir: Path = _path_env("ARTIFACTS_DIR", "artifacts")
    datasets_dir: Path = _path_env("DATASETS_DIR", "datasets")

    @property
    def runs_dir(self) -> Path:
        return self.artifacts_dir / "runs"


def load_settings() -> Settings:
    """Load settings, honouring a local .env if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return Settings()
