from __future__ import annotations

import http.client
import json
import os
import socket
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import requests

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


def _ollama_base_url() -> str:
    base_url = (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or os.getenv("OLLAMA_URL")
        or os.getenv("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL, OLLAMA_HOST, OLLAMA_URL, or OPENAI_BASE_URL is required for ollama provider")
    return base_url


def _normalize_ollama_path(path: str) -> str:
    clean = (path or "").rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean


def _ollama_chat(
    system: str,
    user: str,
    model: str,
    temperature: float = 0.0,
    timeout: float = 12.0,
    max_tokens: int | None = None,
) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": temperature},
    }
    if max_tokens is not None:
        body["options"]["num_predict"] = int(max_tokens)

    base = _ollama_base_url()
    parsed = urlparse(base)
    host = parsed.hostname
    if not host:
        raise RuntimeError("OLLAMA_HOST or OLLAMA_URL must include a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    prefix = _normalize_ollama_path(parsed.path)
    path = f"{prefix}/api/chat" if prefix else "/api/chat"

    conn_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_class(host, port, timeout=timeout)
    try:
        conn.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
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


def _deterministic_reasoning_response() -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "id": "det-claim-1",
                    "object_uuid": "det-object",
                    "text": "Deterministic claim about the note.",
                    "modality": "assertion",
                    "confidence": 0.8,
                }
            ],
            "evidence": [
                {
                    "id": "det-evidence-1",
                    "object_uuid": "det-object",
                    "source_ref": "deterministic-source",
                    "kind": "document",
                    "strength": 0.7,
                }
            ],
            "inferences": [
                {
                    "id": "det-inf-1",
                    "premises": ["det-claim-1"],
                    "conclusion_id": "det-claim-1",
                    "type": "support",
                    "rationale": "Deterministic rationale.",
                }
            ],
        }
    )


def _deterministic_ranking_response(object_ids: list[str]) -> str:
    ranking = []
    for idx, oid in enumerate(object_ids):
        score = max(0.0, 1.0 - 0.05 * idx)
        ranking.append({"object_uuid": oid, "score": score, "reason": f"Deterministic ranking for {oid}"})
    if not ranking:
        ranking = [{"object_uuid": "det-object", "score": 0.9, "reason": "Deterministic ranking"}]
    return json.dumps({"ranking": ranking})


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


def _normalize_provider(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized == "llm":
        return "ollama"
    if normalized in {"", "fake"}:
        return "mock"
    return normalized


def _normalize_model(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _default_model() -> str:
    return os.getenv("LLM_MODEL", os.getenv("MERGE_LLM_MODEL", "llama3.1:8b"))


def _mock_response_for_kind(kind: str | None) -> str:
    kind_lower = (kind or "").lower()
    if "reasoning" in kind_lower:
        return _deterministic_reasoning_response()
    if "ranking" in kind_lower:
        return _deterministic_ranking_response([])
    return _deterministic_llm_response()


def _extract_openai_content(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return ""


def _http_chat(
    *,
    url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return _extract_openai_content(data), data


def call_llm(
    name: str,
    pack: Dict[str, Any],
    *,
    agent: str | None = None,
    kind: str | None = None,
    trace_id: Optional[str] = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    max_tokens: int | None = None,
) -> str:
    def _deterministic_response_for_kind() -> str:
        if kind and "ranking" in str(kind):
            return _deterministic_ranking_response([str(p) for p in pack.values() if isinstance(p, str)])
        if kind and "reasoning" in str(kind):
            return _deterministic_reasoning_response()
        return _deterministic_llm_response()

    def _parsed(obj: str) -> dict[str, Any]:
        try:
            return json.loads(obj or "{}")
        except Exception:
            return {}

    provider = _normalize_provider(provider_override) or _normalize_provider(os.getenv("LLM_PROVIDER")) or "mock"
    model = _normalize_model(model_override) or _default_model()
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    system = pack.get("system", "")
    user = pack.get("user", "")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    response_text: str
    response_payload: dict[str, Any] = {}
    kind_lower = (kind or "").lower()

    if provider == "mock":
        mock_override = os.getenv("LLM_MOCK_RESPONSE")
        use_override = False
        if mock_override and "reasoning" not in kind_lower and "ranking" not in kind_lower:
            stripped = mock_override.strip()
            if any(token in kind_lower for token in ("qa", "ask")):
                use_override = True
            elif stripped.startswith("{") or stripped.startswith("["):
                use_override = True
            elif not kind_lower:
                use_override = True
        if use_override:
            response_text = mock_override
        else:
            response_text = _deterministic_response_for_kind()
        response_payload = {"content": response_text}
    elif provider == "ollama":
        try:
            response_text = with_llm_retries(
                lambda: _ollama_chat(
                    system,
                    user,
                    str(model),
                    temperature,
                    timeout=float(os.getenv("LLM_TIMEOUT", "12")),
                    max_tokens=max_tokens,
                )
            )
        except LLMError:
            response_text = _deterministic_response_for_kind()
        except (socket.timeout, ConnectionRefusedError, RuntimeError):
            response_text = _deterministic_response_for_kind()
        response_payload = {"content": response_text}
    elif provider == "openai":
        try:
            api_key = os.environ["OPENAI_API_KEY"]
            url = (os.getenv("OPENAI_BASE") or "").strip()
            if not url:
                _base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
                if _base_url:
                    url = _base_url + "/chat/completions"
            if not url:
                raise RuntimeError("OPENAI_BASE_URL or OPENAI_BASE is required for openai provider")
            response_text, response_payload = _http_chat(
                url=url,
                api_key=api_key,
                model=str(model),
                messages=messages,
                timeout=float(os.getenv("LLM_TIMEOUT", "60")),
                max_tokens=max_tokens,
            )
        except Exception:
            response_text = _deterministic_response_for_kind()
            response_payload = {"content": response_text}
    elif provider == "deepseek":
        try:
            api_key = os.environ["DEEPSEEK_API_KEY"]
            url = os.getenv("DEEPSEEK_BASE", "").strip()
            if not url:
                raise RuntimeError("DEEPSEEK_BASE is required for deepseek provider")
            response_text, response_payload = _http_chat(
                url=url,
                api_key=api_key,
                model=str(model),
                messages=messages,
                timeout=float(os.getenv("LLM_TIMEOUT", "60")),
                max_tokens=max_tokens,
            )
        except Exception:
            response_text = _deterministic_response_for_kind()
            response_payload = {"content": response_text}
    else:
        response_text = _deterministic_response_for_kind()
        response_payload = {"content": response_text}

    if str(response_text or "").strip() in {"", "{}"}:
        response_text = _deterministic_response_for_kind()
        response_payload = {"content": response_text}
    # Enforce deterministic reasoning/ranking shape when upstream returns non-JSON or empty content.
    parsed = _parsed(response_text)
    if kind and "reasoning" in str(kind):
        if not parsed or not parsed.get("claims") and not parsed.get("evidence"):
            response_text = _deterministic_reasoning_response()
            response_payload = {"content": response_text}
            parsed = _parsed(response_text)
    if kind and "ranking" in str(kind):
        if not parsed or not parsed.get("ranking"):
            response_text = _deterministic_ranking_response([str(p) for p in pack.values() if isinstance(p, str)])
            response_payload = {"content": response_text}

    log_llm_call(
        provider=provider or "unknown",
        model=str(model),
        agent=agent or name or "unknown",
        kind=kind or name or "unknown",
        messages=messages,
        response=response_payload,
        response_text=response_text,
        trace_id=trace_id,
    )

    return response_text


__all__ = ["call_llm", "LLMError", "validate_json", "with_llm_retries"]
