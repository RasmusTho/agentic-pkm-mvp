from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _max_len() -> int:
    return 1000 if TRACE_DETAIL != "preview" else 300


def _build_response_preview(structured: str | None, response_text: str | None, raw: Any, limit: int) -> str:
    def _truncate(val: str) -> str:
        val = val or ""
        return val[:limit] + ("..." if len(val) > limit else "")

    if structured:
        stripped = structured.strip()
        if stripped and stripped not in {"{}", "[]"}:
            return _truncate(stripped)
    if response_text:
        stripped = response_text.strip()
        if stripped:
            return _truncate(stripped)
    if raw is not None:
        try:
            return _truncate(repr(raw))
        except Exception:
            pass
    return "<no-response>"


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

        def preview(text: str, limit: int = 400) -> str:
            text = text or ""
            return text[:limit] + ("..." if len(text) > limit else "")

        prompt_text = "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in messages)
        mode = ""
        if kind.startswith("reasoning."):
            mode = kind.split(".", 1)[1] if "." in kind else ""
        content = response_text or ""
        raw_preview = ""
        try:
            if isinstance(response, (dict, list)):
                raw_preview = json.dumps(response, ensure_ascii=False)
            else:
                raw_preview = str(response)
        except Exception:
            raw_preview = ""
        try:
            if not content and isinstance(response, dict):
                choices = response.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or ""
                if not content:
                    content = str(response.get("content") or response.get("response") or "")
            if not content:
                content = str(response)
        except Exception:
            content = response_text or ""

        preview_text = _build_response_preview(content, response_text, response, _max_len())
        inferred_status = status or ("ok" if preview_text and preview_text not in {"{}", "<no-response>"} else "failed")

        record = {
            "timestamp": time.time(),
            "trace_id": trace_id or str(uuid.uuid4()),
            "provider": provider,
            "model": model,
            "agent": agent,
            "kind": kind,
            "mode": mode,
            "status": inferred_status,
            "prompt_preview": preview(prompt_text, _max_len()),
            "response_preview": preview(preview_text, _max_len()),
            "raw_response_preview": preview(raw_preview, _max_len()),
            "response_text_preview": preview(response_text or "", _max_len()),
        }

        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


__all__ = ["log_llm_call", "TRACE_ENABLED", "TRACE_PATH", "TRACE_DETAIL"]
