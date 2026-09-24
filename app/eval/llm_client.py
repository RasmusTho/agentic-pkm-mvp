from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Any

from app.components.llm.fabric import AdapterRuntimeConfig, ChatClient, get_chat_client
from app.components.llm.router import LLMTaskIntent

DEFAULT_MODE = "skip"  # run | skip


@dataclass
class EvalLLMConfig:
    """The resolved Product route used by opt-in evaluation frameworks."""

    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    model: str = ""
    mode: str = DEFAULT_MODE
    chat_client: ChatClient | None = field(default=None, repr=False)


def configure_eval_openai_env() -> EvalLLMConfig:
    """Resolve an exact registry-backed eval target through Product's facade."""
    mode = "run" if os.getenv("EVAL_LLM_MODE", DEFAULT_MODE).strip().lower() == "run" else "skip"
    if mode == "skip":
        return EvalLLMConfig(mode=mode)
    model = os.getenv("EVAL_LLM_MODEL", "").strip()
    if not model:
        raise RuntimeError("Missing eval LLM config: EVAL_LLM_MODEL")
    base_url, base_url_configured = _resolved_eval_override(
        "EVAL_LLM_BASE_URL", "OPENAI_BASE_URL"
    )
    api_key, api_key_configured = _resolved_eval_override(
        "EVAL_LLM_API_KEY", "OPENAI_API_KEY"
    )
    client = get_chat_client(
        LLMTaskIntent(task_kind="eval"),
        model_id=model,
        adapter_runtime_config=AdapterRuntimeConfig(
            base_url=base_url if base_url_configured else None,
            api_key=api_key if api_key_configured else None,
        ),
    )
    return EvalLLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=client.route.model,
        mode=mode,
        chat_client=client,
    )


def _resolved_eval_override(primary: str, fallback: str) -> tuple[str, bool]:
    if primary in os.environ:
        return os.environ[primary].strip(), True
    if fallback in os.environ:
        return os.environ[fallback].strip(), True
    return "", False


def _output_schema(schema: Any | None) -> dict[str, Any] | None:
    if schema is None:
        return None
    model_json_schema = getattr(schema, "model_json_schema", None)
    if not callable(model_json_schema):
        raise TypeError("eval structured output schema must be a Pydantic model")
    return model_json_schema()


def build_deepeval_model(cfg: EvalLLMConfig) -> Any:
    """Wrap the shared Product ChatClient in DeepEval's custom-model protocol."""
    if cfg.mode != "run" or cfg.chat_client is None:
        raise RuntimeError("evaluation is disabled or has no resolved Product route")
    try:
        from deepeval.models.base_model import DeepEvalBaseLLM  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("deepeval DeepEvalBaseLLM is unavailable") from exc

    class RouterBackedDeepEvalModel(DeepEvalBaseLLM):
        def __init__(self, client: ChatClient, model_name: str) -> None:
            object.__setattr__(self, "_product_chat_client", client)
            object.__setattr__(self, "_product_model_name", model_name)
            super().__init__()

        def load_model(self) -> ChatClient:
            return self._product_chat_client

        def generate(self, prompt: str, schema: Any | None = None) -> Any:
            output_schema = _output_schema(schema)
            response = self.load_model().chat(
                "eval",
                {
                    "system": "You are an evaluation judge. Follow the requested evaluation format.",
                    "user": prompt,
                },
                kind="eval",
                response_format=output_schema,
            )
            if schema is None:
                return response
            return schema.model_validate_json(response)

        async def a_generate(self, prompt: str, schema: Any | None = None) -> Any:
            return await asyncio.to_thread(self.generate, prompt, schema)

        def get_model_name(self) -> str:
            return self._product_model_name

    return RouterBackedDeepEvalModel(cfg.chat_client, cfg.model)


def build_ragas_model(cfg: EvalLLMConfig) -> Any:
    """Return a LangChain LLM bridge for Ragas, backed only by Product ChatClient."""
    if cfg.mode != "run" or cfg.chat_client is None:
        raise RuntimeError("evaluation is disabled or has no resolved Product route")
    try:
        from langchain_core.language_models.llms import LLM
        from pydantic import PrivateAttr
    except Exception as exc:  # pragma: no cover - core dependency should exist
        raise ImportError("LangChain LLM compatibility layer is unavailable") from exc

    class RouterBackedRagasLLM(LLM):
        _product_chat_client: Any = PrivateAttr()
        _product_model_name: str = PrivateAttr()

        def __init__(self, client: ChatClient, model_name: str) -> None:
            super().__init__()
            self._product_chat_client = client
            self._product_model_name = model_name

        @property
        def _llm_type(self) -> str:
            return "product_model_access_router"

        @property
        def _identifying_params(self) -> dict[str, Any]:
            return {"model": self._product_model_name}

        def _call(self, prompt: str, stop=None, run_manager=None, **kwargs: Any) -> str:
            return self._product_chat_client.chat(
                "eval",
                {
                    "system": "You are an evaluation judge. Follow the requested evaluation format.",
                    "user": prompt,
                },
                kind="eval",
            )

    return RouterBackedRagasLLM(cfg.chat_client, cfg.model)


__all__ = [
    "configure_eval_openai_env",
    "EvalLLMConfig",
    "build_deepeval_model",
    "build_ragas_model",
]
