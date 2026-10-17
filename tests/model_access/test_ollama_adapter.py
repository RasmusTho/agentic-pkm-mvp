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


def test_explicit_endpoint_keeps_loopback_guard() -> None:
    adapter = OllamaHttpAdapter(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )
    adapter.close()

    with pytest.raises(TypeError):
        OllamaHttpAdapter()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="host-local HTTP origin"):
        OllamaHttpAdapter(base_url="http://192.0.2.1:11434")


@pytest.mark.parametrize("execution_timeout", [1.5, 1260.0])
def test_metadata_timeout_remains_short_with_long_inference_window(
    execution_timeout: float,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding"]})
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"model": MODEL, "embeddings": [[0.5]]})

    adapter = OllamaHttpAdapter(
        base_url=BASE_URL, timeout_seconds=execution_timeout,
        transport=httpx.MockTransport(respond),
    )
    try:
        adapter.list_models()
        adapter.preflight_embedding(model=MODEL)
        adapter.embed(model=MODEL, input_text="synthetic timeout test", dimensions=1)
    finally:
        adapter.close()

    assert [request.url.path for request in requests] == [
        "/api/tags", "/api/tags", "/api/show", "/api/embed"
    ]
    for request in requests:
        expected = (
            execution_timeout if request.url.path == "/api/embed"
            else min(execution_timeout, 120.0)
        )
        assert request.extensions["timeout"] == {
            phase: expected for phase in ("connect", "read", "write", "pool")
        }


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
