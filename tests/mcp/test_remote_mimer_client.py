"""ADR-0070 remote MCP entrypoint: composed protocol acceptance for #6668.

The real runtime app sits behind the real remote ingress; the real entrypoint (OAuth bearer gate,
Streamable HTTP MCP SDK, v1 semantic layer) is driven over HTTP with JSON-RPC.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from pathlib import Path

import httpx
import pytest

pytest.importorskip("mcp")
pytest.importorskip("mimer_mcp_sidecar")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import app  # noqa: E402
from app.api.remote_ingress import CREDENTIAL_HEADER, RemoteIngress  # noqa: E402
from app.remote_mcp import entrypoint  # noqa: E402
from app.remote_mcp.grant import issue_grant, revoke_grant  # noqa: E402
from app.remote_mcp.oauth import REDIRECT_URI, AuthorizationServer, provision  # noqa: E402
from tests.api.test_multi_vault_governed_writes import setup_capture  # noqa: E402

ISSUER = "https://mimer.example.ts.net"
RESOURCE = f"{ISSUER}/mcp"
OWNER = "owner@example.invalid"
PROTOCOL = "2025-06-18"


class Rig:
    def __init__(
        self, tmp_path: Path, monkeypatch, *, tools=("mimer.health", "mimer.capture")
    ) -> None:
        _runtime, self.first, self.other, _local, self.carrier = setup_capture(
            tmp_path, monkeypatch
        )
        self.grant_path = tmp_path / "grant.json"
        _grant, self.credential = issue_grant(
            self.grant_path, vault_binding_id=self.other.vault_binding_id, tools=tools, days=1
        )
        config, self.client_secret = provision(
            tmp_path / "oauth.json",
            issuer=ISSUER,
            resource=RESOURCE,
            authorization_origin=f"{ISSUER}:8443",
            owner_login=OWNER,
            store_path=tmp_path / "oauth.sqlite3",
            grant_path=self.grant_path,
        )
        self.oauth = AuthorizationServer(config)
        self.ingress = TestClient(
            RemoteIngress(app, grant_path=self.grant_path),
            headers={CREDENTIAL_HEADER.decode(): self.credential},
        )

    def access_token(self) -> str:
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        consent = self.oauth.begin_authorization(
            {
                "response_type": ["code"],
                "client_id": [self.oauth.config.client_id],
                "redirect_uri": [REDIRECT_URI],
                "code_challenge": [challenge],
                "code_challenge_method": ["S256"],
                "state": ["s"],
                "resource": [RESOURCE],
            },
            owner=OWNER,
        )
        location = self.oauth.decide(
            request_id=consent.request_id, csrf=consent.csrf, owner=OWNER, approve=True
        )
        code = location.split("code=", 1)[1].split("&", 1)[0]
        issued = self.oauth.exchange(
            {
                "grant_type": ["authorization_code"],
                "code": [code],
                "redirect_uri": [REDIRECT_URI],
                "code_verifier": [verifier],
                "client_id": [self.oauth.config.client_id],
                "client_secret": [self.client_secret],
            },
            authorization=None,
        )
        return str(issued["access_token"])

    def entry(self, client: httpx.Client | None = None) -> TestClient:
        return TestClient(entrypoint.build_app(self.oauth, client or self.ingress), base_url=ISSUER)

    def inbox(self, registration) -> str:
        path = Path(registration.path, "Inbox/inbox.md")
        return path.read_text() if path.exists() else ""


def rpc(
    client: TestClient,
    token: str | None,
    method: str,
    params: dict | None = None,
    *,
    rid: int = 1,
    headers: dict | None = None,
) -> httpx.Response:
    sent = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL,
        **({"Authorization": f"Bearer {token}"} if token else {}),
        **(headers or {}),
    }
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return client.post("/mcp", content=json.dumps(body), headers=sent)


def tool_payload(response: httpx.Response) -> tuple[bool, dict]:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


def test_remote_client_preserves_governed_authority_and_v1_compatibility(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    token = rig.access_token()
    from mimer_mcp_sidecar.semantic import MimerMcpServer

    v1 = {tool.name: tool.as_dict() for tool in MimerMcpServer(None).list_tools()}
    with rig.entry() as client:
        init = rpc(
            client,
            token,
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "claude", "version": "test"},
            },
        )
        assert init.status_code == 200
        assert init.json()["result"]["serverInfo"]["name"] == "mimer-mcp"
        assert init.json()["result"]["protocolVersion"] == PROTOCOL

        listed = rpc(client, token, "tools/list").json()["result"]["tools"]
        assert sorted(tool["name"] for tool in listed) == ["mimer.capture", "mimer.health"]
        for tool in listed:  # the delivered v1 definitions, unchanged (incl. truthful annotations)
            assert tool["inputSchema"] == v1[tool["name"]]["inputSchema"]
            assert tool.get("annotations") == v1[tool["name"]].get("annotations")

        is_error, health = tool_payload(
            rpc(client, token, "tools/call", {"name": "mimer.health", "arguments": {}})
        )
        assert is_error is False and "result" in health

        is_error, captured = tool_payload(
            rpc(
                client,
                token,
                "tools/call",
                {
                    "name": "mimer.capture",
                    "arguments": {"text": "Remote MCP boiler note", "trace_id": "remote-trace-1"},
                },
            )
        )
    assert is_error is False, captured
    envelope = captured["result"]
    assert captured["trace_id"] == "remote-trace-1"
    assert envelope["outcome"] == "written"
    receipt = envelope["governed_write"]["authority_receipt"]
    assert receipt["outcome"] == "applied" and receipt["fallback_used"] is False
    assert receipt["actor"] == "companion.capture"
    context = receipt["active_context"]
    assert [b["vault_binding_id"] for b in context["source_bindings"]] == [
        rig.other.vault_binding_id
    ]
    assert context["selection_provenance"] == "remote_grant"
    assert context["principal_context"]["subject"] == "remote_mcp_grant"
    assert "Remote MCP boiler note" in rig.inbox(rig.other)
    assert "Remote MCP boiler note" not in rig.inbox(rig.first)


def test_remote_entrypoint_rejects_unauthorized_and_cross_vault_calls(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    token = rig.access_token()
    with rig.entry() as client:
        for presented in (None, "not-a-token"):
            refused = rpc(client, presented, "tools/list")
            assert refused.status_code == 401
            challenge = refused.headers["www-authenticate"]
            assert challenge.startswith("Bearer ")
            assert (
                'resource_metadata="https://mimer.example.ts.net/.well-known/oauth-protected-resource/mcp"'
                in challenge
            )
        # The discovery the challenge points at is served by the same listener.
        assert (
            client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == RESOURCE
        )

        # Operations outside the grant are neither listed nor callable, whatever the arguments.
        for name, arguments in (
            ("mimer.ask", {"question": "What is in the vault?"}),
            ("mimer.retrieve", {"query": "boiler"}),
            ("mimer.read_note", {"note_path": "../first/Inbox/inbox.md"}),
            ("vault.write", {"path": "/etc/passwd"}),
        ):
            is_error, payload = tool_payload(
                rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
            )
            assert (is_error, payload["error"]) == (True, "tool_not_granted")

        # Confused deputy: an argument cannot name a binding; forged identity headers grant nothing.
        is_error, payload = tool_payload(
            rpc(
                client,
                token,
                "tools/call",
                {
                    "name": "mimer.capture",
                    "arguments": {
                        "text": "Cross vault",
                        "target_binding_id": rig.first.vault_binding_id,
                    },
                },
                headers={
                    **rig.carrier,
                    "Tailscale-User-Login": OWNER,
                    "X-Forwarded-For": "127.0.0.1",
                },
            )
        )
        assert is_error is True and payload["error"] == "validation_error"
        is_error, payload = tool_payload(
            rpc(
                client,
                token,
                "tools/call",
                {
                    "name": "mimer.capture",
                    "arguments": {"text": "Forged headers"},
                },
                headers={**rig.carrier, "Tailscale-User-Login": OWNER, "X-API-Key": "x"},
            )
        )
        assert is_error is False
        # DNS rebinding of the loopback listener: a foreign Host is refused by the transport.
        rebound = TestClient(
            entrypoint.build_app(rig.oauth, rig.ingress), base_url="http://127.0.0.1:9000"
        )
        with rebound:
            assert rpc(rebound, token, "tools/list").status_code in {403, 421}

        # Revoked or expired runtime grant: the token stops working on the next request.
        revoke_grant(rig.grant_path)
        assert rpc(client, token, "tools/list").status_code == 401

    assert "Cross vault" not in rig.inbox(rig.first) + rig.inbox(rig.other)
    assert "Forged headers" in rig.inbox(rig.other) and "Forged headers" not in rig.inbox(rig.first)


def test_remote_entrypoint_lists_only_the_granted_subset(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, tools=("mimer.health",))
    token = rig.access_token()
    with rig.entry() as client:
        listed = rpc(client, token, "tools/list").json()["result"]["tools"]
        assert [tool["name"] for tool in listed] == ["mimer.health"]
        is_error, payload = tool_payload(
            rpc(
                client,
                token,
                "tools/call",
                {
                    "name": "mimer.capture",
                    "arguments": {"text": "Health only"},
                },
            )
        )
        assert (is_error, payload["error"]) == (True, "tool_not_granted")
    assert "Health only" not in rig.inbox(rig.other)


class _LoseResponseAfterWrite(httpx.BaseTransport):
    """Forward the request (the append lands), then lose the response like a dropped connection."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.inner.handle_request(request).read()
        raise httpx.ReadTimeout("response lost", request=request)


def test_remote_transport_failure_recovery_and_disable(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    rig = Rig(tmp_path, monkeypatch)
    token = rig.access_token()
    lossy = _LoseResponseAfterWrite(rig.ingress._transport)
    lossy_client = httpx.Client(
        transport=lossy,
        base_url="http://testserver",
        headers={CREDENTIAL_HEADER.decode(): rig.credential},
    )

    # Disconnect after write: ambiguous, not retryable, and the adapter does not retry.
    with rig.entry(lossy_client) as client:
        is_error, payload = tool_payload(
            rpc(
                client,
                token,
                "tools/call",
                {
                    "name": "mimer.capture",
                    "arguments": {"text": "Ambiguous boiler note"},
                },
            )
        )
    assert is_error is True
    assert payload["error"] == "capture_ambiguous" and payload["retryable"] is False
    assert lossy.calls == 1
    assert rig.inbox(rig.other).count("Ambiguous boiler note") == 1

    # Restart: a fresh entrypoint has no request state to replay; the append stays single.
    with rig.entry() as client:
        is_error, _health = tool_payload(
            rpc(client, token, "tools/call", {"name": "mimer.health", "arguments": {}})
        )
        assert is_error is False
    assert rig.inbox(rig.other).count("Ambiguous boiler note") == 1

    # Disable: revoking the host grant ends the token at the entrypoint and the credential at the ingress.
    revoke_grant(rig.grant_path)
    with rig.entry() as client:
        assert rpc(client, token, "tools/list").status_code == 401
    assert rig.ingress.get("/healthz").status_code == 403

    # Redaction: no token, credential, client secret, or capture text in our logs.
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("mimer."))
    for secret in (token, rig.credential, rig.client_secret, "Ambiguous boiler note"):
        assert secret not in ours
    # Library diagnostics that may carry payloads are silenced in the process entrypoint.
    entrypoint.quiet_library_diagnostics()
    try:
        for name in ("mcp.server.lowlevel.server", "httpx", "uvicorn.error"):
            assert not logging.getLogger(name).isEnabledFor(logging.CRITICAL)
    finally:
        for name in entrypoint._QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
            logging.getLogger(name).propagate = True
        for handler in logging.getLogger().handlers:
            handler.filters = [
                f for f in handler.filters if not isinstance(f, entrypoint._DropLibraryRecords)
            ]


def test_remote_entrypoint_configuration_refuses_the_ordinary_api(tmp_path):
    for address in ("http://127.0.0.1:8000", "127.0.0.1:8000", "localhost:8000", "relative.sock"):
        with pytest.raises(ValueError):
            entrypoint.EntrypointConfig.build(
                oauth_config=tmp_path / "o.json",
                ingress=address,
                credential_file=tmp_path / "c",
                port=8765,
            )
    regular = tmp_path / "not-a-socket"
    regular.write_text("")
    with pytest.raises(ValueError):
        entrypoint.ingress_client(regular, "credential")
    credential = tmp_path / "credential"
    credential.write_text("abc\n")
    credential.chmod(0o644)
    with pytest.raises(Exception):
        entrypoint.read_credential(credential)
    credential.chmod(0o600)
    assert entrypoint.read_credential(credential) == "abc"
