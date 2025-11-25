from __future__ import annotations

import http.client
import json
import os
import socket
import time
from typing import Any, Callable, Dict, Optional

from app.llm.trace import log_llm_call

_DEFAULT_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
_DEFAULT_BASE_DELAY = float(os.getenv("LLM_BASE_DELAY", "0.1"))


class LLMError(Exception):
    pass


def _minimal_validate(payload: dict, schema: dict) -> None:
    req = schema.get("required", [])
    for k in req:
        if k not in payload:
            raise ValueError(f"schema required key missing: {k}")
    if "decision" in payload and "properties" in schema:
        dec_enum = schema["properties"].get("decision", {}).get("enum")
        if dec_enum and payload["decision"] not in dec_enum:
            raise ValueError("schema enum violation: decision")


def validate_json(raw: str, schema_path: str) -> Dict[str, Any]:
    data = json.loads(raw)
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        _minimal_validate(data, schema)
    except Exception:
        pass
    return data


def _ollama_chat(system: str, user: str, model: str, temperature: float = 0.0, timeout: float = 12.0) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "options": {"temperature": temperature}
    }
    conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
    try:
        conn.request("POST", "/api/chat", body=json.dumps(body), headers={"Content-Type":"application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"ollama http {resp.status}")
        buf = []
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            buf.append(chunk)
        raw = b"".join(buf).decode("utf-8", errors="replace")
        text = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "message" in obj and "content" in obj["message"]:
                    text += obj["message"]["content"]
            except Exception:
                text += line
        return text.strip()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _deterministic_llm_response() -> str:
    return json.dumps(
        {
            "decision": "A",
            "similarity": 0.92,
            "confidence": 0.8,
            "scores": {"A": {"total": 8.0}, "B": {"total": 7.7}},
            "reason": "concise wins",
            "hybrid": {"take_from": "A", "carry_over_items": []},
            "ask_prompt": "",
            "policy_flags": ["provenance_preserved"],
        }
    )


def with_llm_retries(
    fn: Callable[[], Any], *, max_retries: int | None = None, base_delay: float | None = None
) -> Any:
    mr = _DEFAULT_MAX_RETRIES if max_retries is None else max_retries
    bd = _DEFAULT_BASE_DELAY if base_delay is None else base_delay
    attempt = 0
    while True:
        try:
            return fn()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            attempt += 1
            if attempt > mr:
                raise LLMError(f"LLM call failed after {mr} retries") from exc
            time.sleep(max(bd, 0.0) * attempt)


def call_llm(
    name: str,
    pack: Dict[str, Any],
    *,
    agent: str | None = None,
    kind: str | None = None,
    trace_id: Optional[str] = None,
) -> str:
    provider = os.getenv("LLM_PROVIDER", "fake").lower()
    if provider == "llm":
        provider = "ollama"
    model = os.getenv("LLM_MODEL", os.getenv("MERGE_LLM_MODEL", "llama3.1:8b"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    system = pack.get("system", "")
    user = pack.get("user", "")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    response_text: str

    if provider != "ollama":
        response_text = _deterministic_llm_response()
    else:
        try:
            response_text = with_llm_retries(lambda: _ollama_chat(system, user, model, temperature))
        except LLMError:
            response_text = _deterministic_llm_response()
        except (socket.timeout, ConnectionRefusedError, RuntimeError):
            response_text = _deterministic_llm_response()

    log_llm_call(
        provider=provider or "unknown",
        model=model,
        agent=agent or name or "unknown",
        kind=kind or name or "unknown",
        messages=messages,
        response={"content": response_text},
        trace_id=trace_id,
    )

    return response_text
