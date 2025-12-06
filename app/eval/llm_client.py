from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY = "sk-local"


@dataclass
class EvalLLMConfig:
    base_url: str
    api_key: str
    mode: str = "live"  # live | mock | skip


def configure_eval_openai_env() -> EvalLLMConfig:
    """
    Configure OpenAI-compatible environment variables for eval runs.

    Intended for local DeepEval/Ragas tests that talk to an OpenAI-compatible endpoint,
    typically Ollama (e.g., llama3.1:8b) exposed via `OPENAI_BASE_URL`.
    """
    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL).strip()
    api_key = os.getenv("OPENAI_API_KEY", DEFAULT_API_KEY).strip()
    mode = os.getenv("EVAL_LLM_MODE", "").strip().lower() or "live"

    os.environ.setdefault("OPENAI_BASE_URL", base_url or DEFAULT_BASE_URL)
    os.environ.setdefault("OPENAI_API_KEY", api_key or DEFAULT_API_KEY)

    return EvalLLMConfig(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"], mode=mode)


__all__ = ["configure_eval_openai_env", "EvalLLMConfig"]
