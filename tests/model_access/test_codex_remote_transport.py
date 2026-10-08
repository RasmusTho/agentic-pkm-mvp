from __future__ import annotations

import json
import ssl
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest

from app.model_access import codex_remote_transport as remote_transport_module
from app.model_access.codex_remote_transport import (
    CodexRemoteTransport,
    RemoteCompletionError,
    RemoteCatalogError,
    RemotePreflightError,
)
from app.model_access.catalog import CatalogModelDescriptor, CatalogSnapshot
from app.model_access.remote_contract import (
    CatalogRequest,
    CompletionRequest,
    CompletionResponse,
    CompletionRouteIdentity,
    PreflightRequest,
    PreflightResponse,
    ProductCatalogRequest,
    ProductCompletionRequest,
    ProductPreflightRequest,
)


ENDPOINT = "https://mac-mini.example-tailnet.ts.net"


class _FailingResponseBody(httpx.SyncByteStream):
    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def __iter__(self) -> Iterator[bytes]:
        yield b'{"error":{"code":"PATH_UNAVAILABLE"}}'
        raise self._failure

    def close(self) -> None:
        return None


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


def _catalog_response(transport_id: str = "codex_cli") -> dict[str, object]:
    provider = "openai" if transport_id == "codex_cli" else "ollama"
    model = "gpt-5.6-luna" if transport_id == "codex_cli" else "llama3.1:8b"
    descriptor = CatalogModelDescriptor(
        provider=provider,
        model=model,
        transports=(transport_id,),
        capabilities={},
        reasoning_efforts=("low",) if transport_id == "codex_cli" else (),
    )
    snapshot = CatalogSnapshot.create(
        provider=provider,
        transport_id=transport_id,
        source_id=(
            "codex_app_server_model_list"
            if transport_id == "codex_cli"
            else "ollama_api_tags"
        ),
        fetched_at=datetime.now(timezone.utc),
        models=[descriptor],
    )
    return {"snapshot": snapshot.model_dump(mode="json")}


def test_remote_catalog_is_authenticated_transport_selection_and_hash_bound() -> None:
    request = CatalogRequest(transport_id="codex_cli")
    calls: list[httpx.Request] = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        assert str(http_request.url) == ENDPOINT + "/v1/catalog"
        assert http_request.method == "POST"
        assert "tailscale-app-capabilities" not in http_request.headers
        assert "authorization" not in http_request.headers
        assert json.loads(http_request.content) == {"transport_id": "codex_cli"}
        return httpx.Response(200, json=_catalog_response())

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = transport.catalog(request)
    finally:
        transport.close()

    assert result.snapshot.provider == "openai"
    assert result.snapshot.models[0].model == "gpt-5.6-luna"
    assert result.snapshot.snapshot_hash == result.snapshot.compute_hash()
    assert len(calls) == 1


def test_remote_catalog_rejects_wrong_transport_and_preserves_only_safe_errors() -> None:
    request = CatalogRequest(transport_id="codex_cli")

    def wrong_route(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_catalog_response("ollama_http"))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(wrong_route),
    )
    try:
        with pytest.raises(RemoteCatalogError, match="catalog_transport_mismatch"):
            transport.catalog(request)
    finally:
        transport.close()

    def fail(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": "catalog_unavailable", "detail": "private endpoint secret"}},
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemoteCatalogError) as error:
            transport.catalog(request)
    finally:
        transport.close()
    assert error.value.code == "catalog_unavailable"
    assert "private" not in str(error.value)


def test_remote_catalog_preserves_received_status_when_error_body_read_fails() -> None:
    request = CatalogRequest(transport_id="codex_cli")

    def fail(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            stream=_FailingResponseBody(httpx.ReadError("response body was lost")),
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemoteCatalogError) as error:
            transport.catalog(request)
    finally:
        transport.close()

    assert error.value.code == "catalog_http_403"


def test_remote_catalog_preserves_received_status_for_oversized_error_body() -> None:
    request = CatalogRequest(transport_id="codex_cli")

    def oversized(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            content=b"x" * (remote_transport_module.MAX_CATALOG_RESPONSE_BYTES + 1),
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(oversized),
    )
    try:
        with pytest.raises(RemoteCatalogError) as error:
            transport.catalog(request)
    finally:
        transport.close()

    assert error.value.code == "catalog_http_403"


def test_remote_catalog_unexpected_transport_exception_is_invalid() -> None:
    request = CatalogRequest(transport_id="codex_cli")

    def unexpected(_http_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("unexpected transport adapter failure")

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(unexpected),
    )
    try:
        with pytest.raises(RemoteCatalogError) as error:
            transport.catalog(request)
    finally:
        transport.close()

    assert error.value.code == "catalog_invalid"


def test_remote_preflight_is_route_bound_and_single_request() -> None:
    request = _preflight_request()
    host_route = request.route.model_copy(
        update={
            "catalog_snapshot_ref": "catalog.openai_codex_cli",
            "catalog_snapshot_hash": "sha256:" + "b" * 64,
        }
    )
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
            route=host_route,
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

    assert result.route == host_route
    assert result.preflight_status == "passed"
    assert len(calls) == 1


@pytest.mark.parametrize("code", ["session_expired", "PATH_UNAVAILABLE"])
def test_remote_preflight_preserves_only_typed_failure_codes(code: str) -> None:
    request = _preflight_request()

    def fail(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": code, "detail": "secret data"}},
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

    assert error.value.code == code
    assert "secret" not in str(error.value).lower()


@pytest.mark.parametrize(
    ("status_code", "failure", "expected_code"),
    [
        (403, httpx.ReadTimeout("error body stalled"), "preflight_http_403"),
        (400, httpx.ReadError("error body disconnected"), "preflight_http_400"),
    ],
)
def test_remote_preflight_preserves_received_status_when_error_body_read_fails(
    status_code: int, failure: Exception, expected_code: str
) -> None:
    request = _preflight_request()

    def fail(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, stream=_FailingResponseBody(failure))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == expected_code


def test_remote_preflight_preserves_received_status_for_oversized_error_body() -> None:
    request = _preflight_request()

    def oversized(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            content=b"x" * (remote_transport_module.MAX_PREFLIGHT_RESPONSE_BYTES + 1),
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(oversized),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == "preflight_http_403"


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

    assert error.value.code == "PREFLIGHT_TIMEOUT"
    assert calls == 1


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (httpx.ConnectTimeout("connect timed out"), "CONNECT_TIMEOUT"),
        (httpx.ConnectError("connection refused"), "PATH_UNAVAILABLE"),
        (httpx.ReadTimeout("preflight timed out"), "PREFLIGHT_TIMEOUT"),
    ],
)
def test_remote_preflight_maps_path_local_transport_failures(
    failure: Exception, expected_code: str
) -> None:
    request = _preflight_request()
    calls = 0

    def fail(_http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == expected_code
    assert calls == 1


def test_remote_preflight_classifies_tls_path_authentication_failure() -> None:
    request = _preflight_request()
    calls = 0

    def fail(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        failure = httpx.ConnectError("TLS handshake failed", request=http_request)
        raise failure from ssl.SSLError("private certificate detail")

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == "PATH_AUTHENTICATION_FAILED"
    assert "private certificate" not in str(error.value)
    assert calls == 1


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (httpx.ReadError("connection reset while reading"), "PATH_UNAVAILABLE"),
        (httpx.WriteError("connection reset while writing"), "PATH_UNAVAILABLE"),
    ],
)
def test_remote_preflight_classifies_non_timeout_transport_failures(
    failure: Exception, expected_code: str
) -> None:
    request = _preflight_request()

    def fail(_http_request: httpx.Request) -> httpx.Response:
        raise failure

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(RemotePreflightError) as error:
            transport.preflight(request)
    finally:
        transport.close()

    assert error.value.code == expected_code


def test_remote_preflight_classifies_tls_alert_wrapped_in_read_error() -> None:
    request = _preflight_request()

    def fail(http_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("TLS alert", request=http_request) from ssl.SSLError(
            "private certificate detail"
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

    assert error.value.code == "PATH_AUTHENTICATION_FAILED"
    assert "private certificate" not in str(error.value)


def test_remote_complete_is_route_bound_and_never_retries() -> None:
    request = _request()
    host_route = request.route.model_copy(
        update={
            "catalog_snapshot_ref": "catalog.openai_codex_cli",
            "catalog_snapshot_hash": "sha256:" + "b" * 64,
        }
    )
    calls: list[httpx.Request] = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        assert str(http_request.url) == ENDPOINT + "/v1/complete"
        assert "tailscale-app-capabilities" not in http_request.headers
        assert "authorization" not in http_request.headers
        sent = json.loads(http_request.content)
        assert sent["route"] == request.route.model_dump(mode="json")
        response = CompletionResponse(route=host_route, content="hello")
        return httpx.Response(200, json=response.model_dump(mode="json"))

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = transport.complete(request)
    finally:
        transport.close()

    assert result.route == host_route
    assert result.content == "hello"
    assert len(calls) == 1


def test_product_transport_sends_only_logical_provider_and_model() -> None:
    request = ProductCompletionRequest(
        provider="openai",
        model="gpt-6-luna",
        reasoning_effort="high",
        trusted_instructions="Be concise.",
        user_input="Say hello.",
    )
    preflight_request = ProductPreflightRequest(
        provider="openai", model="gpt-6-luna", reasoning_effort="high"
    )
    host_route = CompletionRouteIdentity(
        provider="openai",
        model="gpt-6-luna",
        transport_id="openai_api",
        catalog_snapshot_ref="catalog.openai_openai_api",
        catalog_snapshot_hash="sha256:" + "c" * 64,
    )
    calls: list[httpx.Request] = []

    def respond(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        sent = json.loads(http_request.content)
        assert "transport_id" not in sent
        assert "catalog_snapshot_ref" not in sent
        if http_request.url.path.endswith("/preflight"):
            assert str(http_request.url) == ENDPOINT + "/v1/product/preflight"
            return httpx.Response(
                200,
                json=PreflightResponse(
                    route=host_route, preflight_status="passed"
                ).model_dump(mode="json"),
            )
        assert str(http_request.url) == ENDPOINT + "/v1/product/complete"
        return httpx.Response(
            200,
            json=CompletionResponse(route=host_route, content="hello").model_dump(
                mode="json"
            ),
        )

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        preflight = transport.preflight(preflight_request)
        completion = transport.complete(request)
    finally:
        transport.close()

    assert preflight.route == host_route
    assert completion.route == host_route
    assert completion.content == "hello"
    assert len(calls) == 2


def test_product_catalog_selects_provider_without_a_transport_field() -> None:
    request = ProductCatalogRequest(provider="openai")
    response_payload = _catalog_response("codex_cli")

    def respond(http_request: httpx.Request) -> httpx.Response:
        assert str(http_request.url) == ENDPOINT + "/v1/product/catalog"
        assert json.loads(http_request.content) == {"provider": "openai"}
        return httpx.Response(200, json=response_payload)

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        catalog = transport.catalog(request)
    finally:
        transport.close()

    assert catalog.snapshot.provider == "openai"
    assert catalog.snapshot.transport_id == "codex_cli"


def test_product_catalog_can_bind_provider_catalog_to_logical_model() -> None:
    request = ProductCatalogRequest(provider="openai", model="gpt-6-luna")
    response_payload = _catalog_response("codex_cli")

    def respond(http_request: httpx.Request) -> httpx.Response:
        assert str(http_request.url) == ENDPOINT + "/v1/product/catalog"
        assert json.loads(http_request.content) == {
            "provider": "openai",
            "model": "gpt-6-luna",
        }
        return httpx.Response(200, json=response_payload)

    transport = CodexRemoteTransport(
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(respond),
    )
    try:
        catalog = transport.catalog(request)
    finally:
        transport.close()

    assert catalog.snapshot.transport_id == "codex_cli"


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


@pytest.mark.parametrize("tls_verify", [False, True])
def test_private_ingress_rejects_unverified_or_system_only_tls(tls_verify: bool) -> None:
    with pytest.raises(ValueError, match="verified mutual TLS"):
        CodexRemoteTransport(
            endpoint="https://192.168.10.25:8443",
            path_adapter="private_https_ingress",
            tls_verify=tls_verify,
            client_certificate=("client.pem", "client.key"),
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://mac-mini.lan:8443",
        "https://public.example.org:8443",
        "https://198.51.100.25:8443",
        "https://203.0.113.25:8443",
    ],
)
def test_private_ingress_rejects_dns_and_non_private_addresses(endpoint: str) -> None:
    with pytest.raises(ValueError, match="host-local private HTTPS"):
        CodexRemoteTransport(
            endpoint=endpoint,
            path_adapter="private_https_ingress",
            tls_verify="/host-only/ca.pem",
            client_certificate=("/host-only/client.pem", "/host-only/client.key"),
        )


def test_private_ingress_passes_explicit_mtls_context_to_httpx(monkeypatch) -> None:
    context = ssl.create_default_context()
    captured = {}

    class _Transport:
        def __init__(self, *, verify, retries):
            captured["verify"] = verify
            captured["retries"] = retries

    class _Client:
        def __init__(self, *, transport, **_kwargs):
            captured["transport"] = transport

        def close(self):
            pass

    monkeypatch.setattr(
        remote_transport_module,
        "_private_ingress_ssl_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(remote_transport_module.httpx, "HTTPTransport", _Transport)
    monkeypatch.setattr(remote_transport_module.httpx, "Client", _Client)

    transport = CodexRemoteTransport(
        endpoint="https://192.168.10.25:8443",
        path_adapter="private_https_ingress",
        tls_verify="/host-only/ca.pem",
        client_certificate=("/host-only/client.pem", "/host-only/client.key"),
    )
    try:
        assert captured["verify"] is context
        assert captured["retries"] == 0
        assert captured["transport"] is not None
    finally:
        transport.close()


def test_private_ingress_context_loads_ca_and_client_chain(monkeypatch) -> None:
    captured = {}

    class _Context:
        verify_mode = None
        check_hostname = False

        def load_cert_chain(self, *, certfile, keyfile):
            captured["certfile"] = certfile
            captured["keyfile"] = keyfile

    context = _Context()

    def create_default_context(*, cafile):
        captured["cafile"] = cafile
        return context

    monkeypatch.setattr(
        remote_transport_module.ssl, "create_default_context", create_default_context
    )
    result = remote_transport_module._private_ingress_ssl_context(
        ca_bundle_path="/host-only/ca.pem",
        client_certificate=("/host-only/client.pem", "/host-only/client.key"),
    )

    assert result is context
    assert captured == {
        "cafile": "/host-only/ca.pem",
        "certfile": "/host-only/client.pem",
        "keyfile": "/host-only/client.key",
    }
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
