from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from app.config.llm import get_provider
from app.llm.trace import log_llm_call


def _prov() -> str:
    return get_provider()


def _model() -> str:
    model = os.getenv("LLM_MODEL", "").strip()
    if not model:
        raise RuntimeError("LLM_MODEL is required")
    return model


def _rmodel() -> str:
    return os.getenv("LLM_REASONING_MODEL", _model())


def generate(
    messages: List[Dict[str, Any]],
    *,
    reasoning: bool = False,
    agent: str = "unknown",
    kind: str = "unknown",
    trace_id: Optional[str] = None,
) -> str:
    p = _prov()
    m = _rmodel() if reasoning else _model()
    raw_response: Dict[str, Any] | Any = {}

    if p == "mock":
        mock = os.getenv("LLM_MOCK_RESPONSE", "UNSURE")
        content = str(mock)
        raw_response = {"content": content}
    elif p == "ollama":
        ollama_host = (
            os.getenv("OLLAMA_BASE_URL", "").strip()
            or os.getenv("OLLAMA_HOST", "").strip()
            or os.getenv("OLLAMA_URL", "").strip()
            or os.getenv("OPENAI_BASE_URL", "").strip()
        )
        if not ollama_host:
            raise RuntimeError("OLLAMA_BASE_URL, OLLAMA_HOST, OLLAMA_URL, or OPENAI_BASE_URL is required for ollama provider")
        r = requests.post(
            ollama_host.rstrip("/") + "/api/chat",
            json={"model": m, "messages": messages, "stream": False},
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        )
        r.raise_for_status()
        raw_response = r.json()
        content = raw_response["message"]["content"]
    elif p == "openai":
        api = os.environ["OPENAI_API_KEY"]
        url = (os.getenv("OPENAI_BASE") or "").strip()
        if not url:
            _base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
            if _base_url:
                url = _base_url + "/chat/completions"
        if not url:
            raise RuntimeError("OPENAI_BASE_URL or OPENAI_BASE is required for openai provider")
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api}", "Content-Type": "application/json"},
            data=json.dumps({"model": m, "messages": messages}),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )
        r.raise_for_status()
        raw_response = r.json()
        content = raw_response["choices"][0]["message"]["content"]
    elif p == "deepseek":
        api = os.environ["DEEPSEEK_API_KEY"]
        url = os.getenv("DEEPSEEK_BASE", "").strip()
        if not url:
            raise RuntimeError("DEEPSEEK_BASE is required for deepseek provider")
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api}", "Content-Type": "application/json"},
            data=json.dumps({"model": m, "messages": messages}),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )
        r.raise_for_status()
        raw_response = r.json()
        content = raw_response["choices"][0]["message"]["content"]
    else:
        raise ValueError("unsupported provider")

    log_llm_call(
        provider=p,
        model=m,
        agent=agent,
        kind=kind,
        messages=messages,
        response=raw_response,
        response_text=content,
        trace_id=trace_id,
    )
    return content
