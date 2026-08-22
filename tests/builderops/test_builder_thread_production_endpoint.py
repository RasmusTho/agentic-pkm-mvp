from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.builderops.builder_thread_endpoint import BuilderThreadEndpointHost, HttpWriterEndpoint
from app.builderops.builder_threads_serialized import (
    BuilderThreadClient,
    BuilderThreadError,
    BuilderThreadWriterHost,
    WriterUnavailableError,
)


def _transport(app: object) -> httpx.MockTransport:
    client = TestClient(app)

    def dispatch(request: httpx.Request) -> httpx.Response:
        response = client.request(request.method, request.url.path, params=request.url.params, content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=response.headers, content=response.content, request=request)

    return httpx.MockTransport(dispatch)


def _endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[HttpWriterEndpoint, BuilderThreadEndpointHost]:
    monkeypatch.setenv("BUILDEROPS_THREAD_WRITER_ROOT", str(tmp_path / "external-vault"))
    monkeypatch.setenv("BUILDEROPS_THREAD_WRITER_VAULT_ID", "builderops-mac-mini")
    host = BuilderThreadEndpointHost(BuilderThreadWriterHost.from_environment(), client_tokens={"codex:desktop": "test-token"})
    monkeypatch.setenv("BUILDEROPS_THREAD_ENDPOINT_URL", "http://testserver")
    monkeypatch.setenv("BUILDEROPS_THREAD_CLIENT_ID", "codex:desktop")
    monkeypatch.setenv("BUILDEROPS_THREAD_CLIENT_TOKEN", "test-token")
    endpoint = HttpWriterEndpoint.from_environment(transport=_transport(host.app()))
    return endpoint, host


def test_sanctioned_client_reaches_serialized_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint, _ = _endpoint(tmp_path, monkeypatch)
    client = BuilderThreadClient(endpoint, client_id="codex:desktop")

    created = client.create(request_id="endpoint-create-4727", actor="codex:desktop", recipient="claude:mac", subject="Endpoint path", content="Please confirm the authenticated writer path.", source_refs=("github:4727",))

    assert created.thread.vault_id == "builderops-mac-mini"
    assert client.read(created.thread.thread_id) == created.thread


def test_endpoint_preserves_builder_thread_authority_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint, host = _endpoint(tmp_path, monkeypatch)
    client = BuilderThreadClient(endpoint, client_id="codex:desktop")

    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        client.create(request_id="endpoint-private-4727", actor="codex:desktop", recipient="claude:mac", subject="Private", content="Bearer token must not cross this endpoint.", source_refs=("github:4727",))
    assert not any("issue" in route.path or "promotion" in route.path or "receipt" in route.path for route in host.app().routes)

    denied = HttpWriterEndpoint(base_url="http://testserver", client_id="codex:desktop", token="wrong-token", transport=_transport(host.app()))
    with pytest.raises(BuilderThreadError, match="authentication failed"):
        denied.inbox("codex:desktop", limit=1)
    unavailable = HttpWriterEndpoint(base_url="http://127.0.0.1:1", client_id="codex:desktop", token="test-token")
    with pytest.raises(WriterUnavailableError):
        unavailable.inbox("codex:desktop", limit=1)
