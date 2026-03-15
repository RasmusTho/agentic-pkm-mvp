from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_MODE = "skip"  # run | skip


@dataclass
class EvalLLMConfig:
    base_url: str
    api_key: str
    model: str
    mode: str = DEFAULT_MODE


def configure_eval_openai_env() -> EvalLLMConfig:
    """
    Configure OpenAI-compatible environment variables for eval runs.

    Intended for local DeepEval/Ragas tests that talk to an OpenAI-compatible endpoint,
    typically Ollama (e.g., llama3.1:8b) exposed via `OPENAI_BASE_URL`.
    """

    base_url = os.getenv("EVAL_LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "")).strip()
    api_key = os.getenv("EVAL_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
    model = os.getenv("EVAL_LLM_MODEL", "").strip()
    mode = os.getenv("EVAL_LLM_MODE", DEFAULT_MODE).strip().lower() or DEFAULT_MODE
    if mode != "run":
        return EvalLLMConfig(base_url=base_url, api_key=api_key, model=model, mode=mode)

    missing = [
        name
        for name, value in (
            ("EVAL_LLM_BASE_URL", base_url),
            ("EVAL_LLM_API_KEY", api_key),
            ("EVAL_LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing eval LLM config: {', '.join(missing)}")

    # Set OpenAI-compatible envs expected by deepeval/clients
    os.environ.setdefault("OPENAI_BASE_URL", base_url)
    os.environ.setdefault("OPENAI_API_KEY", api_key)
    os.environ.setdefault("OPENAI_MODEL", model)

    return EvalLLMConfig(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"], model=model, mode=mode)


def build_deepeval_model(cfg: EvalLLMConfig) -> Any:
    """Return a deepeval OpenAI-compatible model wrapper or raise for unsupported installs.

    Construction is expected to be network-free; callers may still need a reachable endpoint when executing metrics.
    """

    try:
        from deepeval.models import OpenAIModel  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-specific
        raise ImportError(f"deepeval OpenAIModel unavailable: {exc}") from exc

    try:
        return OpenAIModel(model=cfg.model, api_key=cfg.api_key, base_url=cfg.base_url)
    except TypeError as exc:
        # Older deepeval versions may not support base_url; skip in that case.
        raise RuntimeError("deepeval OpenAIModel does not support base_url; upgrade deepeval to run evals") from exc


__all__ = ["configure_eval_openai_env", "EvalLLMConfig", "build_deepeval_model"]
