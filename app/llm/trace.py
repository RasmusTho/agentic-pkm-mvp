from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.observability.redaction import safe_preview

TRACE_ENABLED = os.getenv("LLM_TRACE_ENABLE", "0") == "1"
TRACE_PATH = Path(os.getenv("LLM_TRACE_PATH", "tmp/llm-trace.jsonl"))
TRACE_DETAIL = os.getenv("LLM_TRACE_DETAIL", "preview").strip().lower()


def _trace_enabled() -> bool:
    return os.getenv("LLM_TRACE_ENABLE", "0") == "1"


def _trace_path() -> Path:
    env_path = os.getenv("LLM_TRACE_PATH")
    if env_path:
        return Path(env_path)
    return TRACE_PATH


def _stringify(obj: Any) -> str:
    try:
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, ensure_ascii=False)
        return str(obj)
    except Exception:
        return ""


def _build_prompt_text(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for msg in messages:
        role = msg.get("role", "") if isinstance(msg, dict) else ""
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _select_response_text(response: Dict[str, Any] | Any, response_text: str | None) -> str:
    if response_text:
        return response_text
    try:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
                if content:
                    return str(content)
            direct = response.get("content") or response.get("response") or ""
            if direct:
                return str(direct)
        return _stringify(response)
    except Exception:
        return response_text or ""


def log_llm_call(
    *,
    provider: str,
    model: str,
    agent: str,
    kind: str,
    messages: List[Dict[str, Any]],
    response: Dict[str, Any] | Any,
    response_text: str | None = None,
    trace_id: Optional[str] = None,
    status: str | None = None,
) -> None:
    """
    Append a single JSONL record describing an LLM call.

    This is a no-op unless LLM_TRACE_ENABLE=1 is set.
    """
    if not _trace_enabled():
        return

    try:
        trace_path = _trace_path()
        trace_path.parent.mkdir(parents=True, exist_ok=True)

        prompt_text = _build_prompt_text(messages)
        content_text = _select_response_text(response, response_text)
        raw_repr = _stringify(response)

        mode = ""
        if kind.startswith("reasoning."):
            mode = kind.split(".", 1)[1] if "." in kind else ""

        response_preview = safe_preview(content_text)
        inferred_status = status or ("ok" if response_preview.get("chars", 0) > 0 else "failed")

        record = {
            "timestamp": time.time(),
            "trace_id": trace_id or str(uuid.uuid4()),
            "provider": provider,
            "model": model,
            "agent": agent,
            "kind": kind,
            "mode": mode,
            "status": inferred_status,
            "prompt_preview": safe_preview(prompt_text),
            "response_preview": response_preview,
            "raw_response_preview": safe_preview(raw_repr),
            "response_text_preview": safe_preview(response_text or ""),
        }

        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


__all__ = ["log_llm_call", "TRACE_ENABLED", "TRACE_PATH", "TRACE_DETAIL"]
