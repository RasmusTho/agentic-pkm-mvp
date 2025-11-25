from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

TRACE_ENABLED = os.getenv("LLM_TRACE_ENABLE", "0") == "1"
TRACE_PATH = Path(os.getenv("LLM_TRACE_PATH", "tmp/llm-trace.jsonl"))


def log_llm_call(
    *,
    provider: str,
    model: str,
    agent: str,
    kind: str,
    messages: List[Dict[str, Any]],
    response: Dict[str, Any] | Any,
    trace_id: Optional[str] = None,
) -> None:
    """
    Append a single JSONL record describing an LLM call.

    This is a no-op unless LLM_TRACE_ENABLE=1 is set.
    """
    if not TRACE_ENABLED:
        return

    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)

        def preview(text: str, limit: int = 400) -> str:
            text = text or ""
            return text[:limit] + ("..." if len(text) > limit else "")

        prompt_text = "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in messages)

        content = ""
        try:
            if isinstance(response, dict):
                choices = response.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or ""
                if not content:
                    content = str(response.get("content") or response.get("response") or "")
            if not content:
                content = str(response)
        except Exception:
            content = ""

        record = {
            "timestamp": time.time(),
            "trace_id": trace_id or str(uuid.uuid4()),
            "provider": provider,
            "model": model,
            "agent": agent,
            "kind": kind,
            "prompt_preview": preview(prompt_text),
            "response_preview": preview(content),
        }

        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


__all__ = ["log_llm_call", "TRACE_ENABLED", "TRACE_PATH"]
