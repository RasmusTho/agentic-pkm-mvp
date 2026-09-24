from __future__ import annotations

import json

import httpx
import pytest

from app.model_access.codex_remote_transport import (
    CodexRemoteTransport,
    RemoteCompletionError,
    RemotePreflightError,
)
from app.model_access.remote_contract import (
    CompletionRequest,
    CompletionResponse,
    CompletionRouteIdentity,
    PreflightRequest,
    PreflightResponse,
)


ENDPOINT = "https://mac-mini.example-tailnet.ts.net"


def _request() -> CompletionRequest:
    return CompletionRequest.model_validate(
        {
            "route": {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "transport_id": "codex_cli",
            },
            "reasoning_effort": "low",
            "capability_intent": {
                "structured_output": False,
                "native_tools": False,
                "literal_system_role_required": False,
            },
            "trusted_instructions": "Keep the answer short.",
            "user_input": "Say hello.",
            "output_schema": None,
        }
    )


def _preflight_request() -> PreflightRequest:
    request = _request()
    return PreflightRequest(
        route=request.route,
        reasoning_effort=request.reasoning_effort,
        capability_intent=request.capability_intent,
    )


def test_remote_preflight_is_route_bound_and_single_request() -> None:
    request = _preflight_request()
    calls: list[httpx.Request] = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        assert str(http_request.url) == ENDPOINT + "/v1/preflight"
        assert "tailscale-app-capabilities" not in http_request.headers
        assert "authorization" not in http_request.headers
        sent = json.loads(http_request.content)
        assert sent == request.model_dump(mode="json")
        assert "trusted_instructions" not in sent
        assert "user_input" not in sent
        response = PreflightResponse(
            route=request.route,
            preflight_status="passed",
        )
        return httpx.Response(200, json=response.model_dump(mode="json"))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = transport.preflight(request)
    finally:
        transport.close()

    assert result.route == request.route
    assert result.preflight_status == "passed"
    assert len(calls) == 1


def test_remote_preflight_preserves_only_typed_failure_codes() -> None:
    request = _preflight_request()

    def fail(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": "session_expired", "detail": "secret data"}},
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == "session_expired"
    assert "secret" not in str(error.value).lower()


def test_remote_preflight_transport_failure_is_safe_and_never_retried() -> None:
    request = _preflight_request()
    calls = 0

    def time_out(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response was lost")

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(time_out),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == "preflight_unavailable"
    assert calls == 1


def test_remote_complete_is_route_bound_and_never_retries() -> None:
    request = _request()
    calls: list[httpx.Request] = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        assert str(http_request.url) == ENDPOINT + "/v1/complete"
        assert "tailscale-app-capabilities" not in http_request.headers
        assert "authorization" not in http_request.headers
        sent = json.loads(http_request.content)
        assert sent["route"] == request.route.model_dump(mode="json")
        response = CompletionResponse(route=request.route, content="hello")
        return httpx.Response(200, json=response.model_dump(mode="json"))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = transport.complete(request)
    finally:
        transport.close()

    assert result.route == request.route
    assert result.content == "hello"
    assert len(calls) == 1


def test_remote_complete_timeout_is_indeterminate_and_never_retries() -> None:
    request = _request()
    calls = 0

    def time_out(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response was lost")

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(time_out),
    )
    try:
        with pytest.raises(RemoteCompletionError) as error:
            transport.complete(request)
    finally:
        transport.close()

    assert error.value.code == "execution_indeterminate"
    assert error.value.indeterminate is True
    assert calls == 1


def test_remote_complete_treats_non_200_as_terminal_and_conservatively_indeterminate() -> None:
    request = _request()
    calls = 0

    def reject(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            422, json={"error": {"code": "ollama_schema_violation"}}
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(reject),
    )
    try:
        with pytest.raises(RemoteCompletionError) as error:
            transport.complete(request)
    finally:
        transport.close()

    assert error.value.code == "executor_http_422"
    assert error.value.indeterminate is True
    assert calls == 1


def test_remote_complete_rejects_a_different_returned_route() -> None:
    request = _request()
    calls = 0

    def mismatched(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        other_route = CompletionRouteIdentity(
            provider="ollama", model="llama3.1:8b", transport_id="ollama_http"
        )
        response = CompletionResponse(route=other_route, content="wrong target")
        return httpx.Response(200, json=response.model_dump(mode="json"))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(mismatched),
    )
    try:
        with pytest.raises(RemoteCompletionError, match="executor_route_mismatch"):
            transport.complete(request)
    finally:
        transport.close()
    assert calls == 1


def test_remote_complete_rejects_oversized_response_without_retry() -> None:
    request = _request()
    calls = 0
    response_body = json.dumps(
        CompletionResponse(route=request.route, content="hello").model_dump(
            mode="json"
        ),
        separators=(",", ":"),
    ).encode("utf-8")

    def oversized(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=response_body)

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        max_response_bytes=len(response_body) - 1,
        transport=httpx.MockTransport(oversized),
    )
    try:
        with pytest.raises(RemoteCompletionError) as error:
            transport.complete(request)
    finally:
        transport.close()

    assert error.value.code == "executor_response_too_large"
    assert error.value.indeterminate is True
    assert calls == 1


def test_remote_complete_sanitizes_unpaired_surrogate_response() -> None:
    request = _request()
    calls = 0

    def malformed(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.dumps(
            {"route": request.route.model_dump(mode="json"), "content": "\ud800"}
        ).encode("ascii")
        return httpx.Response(200, content=payload)

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(malformed),
    )
    try:
        with pytest.raises(RemoteCompletionError, match="executor_response_invalid") as error:
            transport.complete(request)
    finally:
        transport.close()

    assert error.value.indeterminate is True
    assert calls == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://mac-mini.example-tailnet.ts.net",
        "https://user:secret@mac-mini.example-tailnet.ts.net",
        "https://198.51.100.7",
        "https://public.example.org",
    ],
)
def test_remote_transport_requires_a_private_verified_https_origin(endpoint: str) -> None:
    with pytest.raises(ValueError, match="private Tailscale HTTPS"):
        CodexRemoteTransport(endpoint=endpoint)
