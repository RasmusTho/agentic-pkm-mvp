"""One bounded, single-request Ollama chat adapter for the local executor host."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

from app.model_access.remote_contract import validate_inline_schema


class OllamaHttpError(RuntimeError):
    """Secret-free adapter failure code; it never includes request/response data."""

    def __init__(self, failure_code: str) -> None:
        self.failure_code = failure_code
        super().__init__(failure_code)


def _require_loopback_base_url(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        loopback = host == "localhost"
        if host is not None and not loopback:
            loopback = ipaddress.ip_address(host).is_loopback
        if (
            parsed.scheme != "http"
            or not loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("unsupported Ollama endpoint")
        port = parsed.port or 11434
        if not 1 <= port <= 65535:
            raise ValueError("unsupported Ollama port")
    except (TypeError, ValueError) as exc:
        raise ValueError("Ollama endpoint must be a host-local HTTP origin") from exc
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return f"http://{authority}/api/chat"


def _strict_json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


class OllamaHttpAdapter:
    """Send exactly one bounded request to the configured loopback Ollama endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 512_000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("Ollama adapter bounds must be positive")
        self._url = _require_loopback_base_url(base_url)
        self._max_output_bytes = max_output_bytes
        client_transport = transport or httpx.HTTPTransport(retries=0)
        self._client = httpx.Client(
            transport=client_transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    def complete(
        self,
        *,
        model: str,
        trusted_instructions: str,
        user_input: str,
        output_schema: dict[str, Any] | None,
        literal_system_role_required: bool,
    ) -> str:
        if output_schema is not None:
            validate_inline_schema(output_schema)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": trusted_instructions},
                {"role": "user", "content": user_input},
            ],
            "stream": False,
        }
        if output_schema is not None:
            payload["format"] = output_schema

        try:
            with self._client.stream("POST", self._url, json=payload) as response:
                if response.status_code != 200:
                    raise OllamaHttpError("ollama_request_failed")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > self._max_output_bytes:
                        raise OllamaHttpError("ollama_output_too_large")
                    body.extend(chunk)
        except OllamaHttpError:
            raise
        except httpx.TimeoutException as exc:
            raise OllamaHttpError("ollama_timeout") from exc
        except httpx.HTTPError as exc:
            raise OllamaHttpError("ollama_unavailable") from exc

        try:
            result = json.loads(
                bytes(body).decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_json_object_pairs,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
            raise OllamaHttpError("ollama_response_invalid") from exc
        if not isinstance(result, dict):
            raise OllamaHttpError("ollama_response_invalid")
        message = result.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaHttpError("ollama_response_invalid")
        if message.get("tool_calls"):
            raise OllamaHttpError("ollama_tools_unavailable")

        content = message["content"]
        if not content or len(content.encode("utf-8")) > self._max_output_bytes:
            raise OllamaHttpError("ollama_output_too_large")
        if output_schema is not None:
            try:
                value = json.loads(
                    content,
                    object_pairs_hook=_strict_json_object_pairs,
                    parse_constant=_reject_json_constant,
                )
                Draft202012Validator(output_schema).validate(value)
            except Exception as exc:
                raise OllamaHttpError("ollama_schema_violation") from exc
        # Ollama's chat endpoint always maps trusted instructions to the explicit system role.
        return content

    def close(self) -> None:
        self._client.close()


__all__ = ["OllamaHttpAdapter", "OllamaHttpError"]
