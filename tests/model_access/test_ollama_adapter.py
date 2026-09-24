from __future__ import annotations

import json

import httpx
import pytest

from app.model_access.ollama_http import OllamaHttpAdapter, OllamaHttpError


BASE_URL = "http://127.0.0.1:11434"
MODEL = "llama3.1:8b"


def _adapter(handler) -> OllamaHttpAdapter:
    return OllamaHttpAdapter(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )


def test_preflight_reports_model_and_declared_capabilities() -> None:
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": MODEL, "model": MODEL}]},
            )
        assert request.method == "POST"
        assert json.loads(request.content) == {"model": MODEL}
        return httpx.Response(
            200,
            json={"capabilities": ["completion", "tools"]},
        )

    adapter = _adapter(respond)
    try:
        result = adapter.preflight(model=MODEL)
    finally:
        adapter.close()

    assert result.model == MODEL
    assert result.model_capabilities == ("completion", "tools")
    assert result.structured_output_supported is True
    # Ollama metadata cannot elevate the current adapter's no-tool ceiling.
    assert result.native_tools_supported is False
    assert calls == [("GET", "/api/tags"), ("POST", "/api/show")]
    assert all(path != "/api/chat" for _method, path in calls)


def test_preflight_refuses_a_model_not_installed_locally() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"models": [{"name": "other:latest"}]})

    adapter = _adapter(respond)
    try:
        with pytest.raises(OllamaHttpError) as error:
            adapter.preflight(model=MODEL)
    finally:
        adapter.close()

    assert error.value.failure_code == "ollama_model_unavailable"
    assert calls == ["/api/tags"]


def test_preflight_refuses_a_local_model_without_completion_capability() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"model": MODEL}]})
        return httpx.Response(200, json={"capabilities": ["embedding"]})

    adapter = _adapter(respond)
    try:
        with pytest.raises(OllamaHttpError) as error:
            adapter.preflight(model=MODEL)
    finally:
        adapter.close()

    assert error.value.failure_code == "ollama_completion_unavailable"


def test_preflight_requires_well_formed_model_capability_metadata() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        return httpx.Response(200, json={"capabilities": "completion"})

    adapter = _adapter(respond)
    try:
        with pytest.raises(OllamaHttpError) as error:
            adapter.preflight(model=MODEL)
    finally:
        adapter.close()

    assert error.value.failure_code == "ollama_model_capabilities_unavailable"


def test_preflight_transport_failure_is_typed_and_secret_free() -> None:
    def unavailable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("http://127.0.0.1:11434 secret endpoint")

    adapter = _adapter(unavailable)
    try:
        with pytest.raises(OllamaHttpError) as error:
            adapter.preflight(model=MODEL)
    finally:
        adapter.close()

    assert error.value.failure_code == "ollama_unavailable"
    assert "127.0.0.1" not in str(error.value)
    assert "secret" not in str(error.value)
