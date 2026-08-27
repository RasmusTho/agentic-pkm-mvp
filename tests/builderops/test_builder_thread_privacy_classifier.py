from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.builderops.builder_thread_endpoint import BuilderThreadEndpointHost, HttpWriterEndpoint
from app.builderops.builder_threads_serialized import (
    BuilderThreadClient,
    BuilderThreadError,
    BuilderThreadWriterHost,
    SerializedThreadWriter,
    initialize_external_writer_root,
)


def _transport(app: object) -> httpx.MockTransport:
    client = TestClient(app)

    def dispatch(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method,
            request.url.path,
            params=request.url.params,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    return httpx.MockTransport(dispatch)


def _http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, client_id: str = "codex:desktop"
) -> tuple[BuilderThreadClient, Path]:
    root = tmp_path / "external-vault"
    monkeypatch.setenv("BUILDEROPS_THREAD_WRITER_ROOT", str(root))
    monkeypatch.setenv("BUILDEROPS_THREAD_WRITER_VAULT_ID", "builderops-mac-mini")
    host = BuilderThreadEndpointHost(
        BuilderThreadWriterHost.from_environment(), client_tokens={client_id: "test-token"}
    )
    endpoint = HttpWriterEndpoint(
        base_url="http://testserver",
        client_id=client_id,
        token="test-token",
        transport=_transport(host.app()),
    )
    return BuilderThreadClient(endpoint, client_id=client_id), root


def _create(
    client: BuilderThreadClient,
    *,
    request_id: str = "privacy-create-5118",
    content: str = "A bounded question.",
    actor: str = "codex:desktop",
    recipient: str = "claude:mac",
    subject: str = "Structural boundary",
    source_refs: tuple[str, ...] = ("github:5118",),
) -> object:
    return client.create(
        request_id=request_id,
        actor=actor,
        recipient=recipient,
        subject=subject,
        content=content,
        source_refs=source_refs,
    )


def test_http_and_recovery_reject_all_persisted_untrusted_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, root = _http_client(tmp_path, monkeypatch)
    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        _create(client, content="https://example.test/ok?next=%252Fprivate%252Fhost")
    for kwargs in (
        {"request_id": "token-request-5118"},
        {"recipient": "token:recipient"},
        {"subject": "token subject"},
        {"source_refs": ("github:token",)},
    ):
        with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
            _create(client, **kwargs)
    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        _http_client(tmp_path / "actor", monkeypatch, client_id="token:client")
    entries = root / "builder-thread-entries"
    assert list(entries.glob("*.json")) == []

    created = _create(client, request_id="recovery-create-5118")
    record = entries / "recovery-create-5118.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["command"]["actor"] = "token:client"
    from app.builderops.builder_threads_serialized import ThreadMutation, _command_digest

    command = ThreadMutation(
        request_id=payload["command"]["request_id"],
        kind=payload["command"]["kind"],
        actor=payload["command"]["actor"],
        recipient=payload["command"]["recipient"],
        subject=payload["command"]["subject"],
        content=payload["command"]["content"],
        source_refs=tuple(payload["command"]["source_refs"]),
    )
    payload["request_digest"] = _command_digest(command)
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuilderThreadError, match="external writer entry is invalid"):
        SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root)
    assert created.thread.thread_id


def test_closed_persisted_record_and_root_identity_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, root = _http_client(tmp_path, monkeypatch)
    _create(client)
    record = root / "builder-thread-entries" / "privacy-create-5118.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuilderThreadError, match="external writer entry is invalid"):
        SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root)

    record.write_text(json.dumps({key: value for key, value in payload.items() if key != "unexpected"}), encoding="utf-8")
    root_identity = root / "builder-thread-writer.json"
    root_identity.write_text(
        '{"schema":"builder-thread-writer.v1","vault_id":"builderops-mac-mini","extra":true}',
        encoding="utf-8",
    )
    with pytest.raises(BuilderThreadError, match="pinned vault identity"):
        SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root)
    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        initialize_external_writer_root(tmp_path / "unsafe-vault", vault_id="token-vault")


def test_structural_privacy_adversarial_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, root = _http_client(tmp_path, monkeypatch)
    accepted = _create(
        client,
        request_id="valid-url-5118",
        content="https://example.test/home/start?view=summary#today",
    )
    assert accepted.replayed is False
    assert len(list((root / "builder-thread-entries").glob("*.json"))) == 1
    assert _create(
        client,
        request_id="valid-url-5118",
        content="https://example.test/home/start?view=summary#today",
    ).replayed is True
    restarted = SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root)
    assert restarted.accepted_mutation_count == 1
    for value in (
        "/tmp/host-only",
        "C:\\\\Users\\\\operator",
        "file:///private/host-only",
        "https://example.test/ok#%252Fprivate%252Fhost",
        "https://[invalid-zone%25?]/ok",
    ):
        with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
            _create(client, request_id=f"refusal-{len(value)}-5118", content=value)
    assert len(list((root / "builder-thread-entries").glob("*.json"))) == 1
