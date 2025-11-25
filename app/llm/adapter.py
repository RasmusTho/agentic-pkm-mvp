from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from app.llm.trace import log_llm_call


def _prov() -> str:
    prov = os.getenv("LLM_PROVIDER", "ollama").lower()
    return "ollama" if prov == "llm" else prov


def _model() -> str:
    return os.getenv("LLM_MODEL", "llama3.1:8b")


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
        r = requests.post(
            os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/chat",
            json={"model": m, "messages": messages, "stream": False},
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        )
        r.raise_for_status()
        raw_response = r.json()
        content = raw_response["message"]["content"]
    elif p == "openai":
        api = os.environ["OPENAI_API_KEY"]
        url = os.getenv("OPENAI_BASE", "https://api.openai.com/v1/chat/completions")
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
        url = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com/chat/completions")
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
