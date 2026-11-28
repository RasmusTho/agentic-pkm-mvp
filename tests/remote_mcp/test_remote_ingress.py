"""ADR-0070 remote ingress: remote subject, grant, route allowlist, pinned binding (#6668)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.app import app
from app.auth import SUBJECT_REMOTE_MCP_GRANT, require_loopback_or_api_key
from app.remote_mcp.grant import (
    GrantRefused,
    admit,
    issue_grant,
    load_grant,
    main as grant_main,
    revoke_grant,
)
from app.api.remote_ingress import CREDENTIAL_HEADER, RemoteIngress
from tests.api.test_multi_vault_governed_writes import setup_capture

_CRED = CREDENTIAL_HEADER.decode()


def _remote(tmp_path: Path, binding: str, tools=("mimer.health", "mimer.capture")):
    grant_path = tmp_path / "remote-grant.json"
    _grant, credential = issue_grant(grant_path, vault_binding_id=binding, tools=tools, days=1)
    return TestClient(RemoteIngress(app, grant_path=grant_path)), grant_path, credential


def _inbox(registration) -> str:
    path = Path(registration.path, "Inbox/inbox.md")
    return path.read_text() if path.exists() else ""


def test_remote_capture_is_pinned_to_the_grant_binding_and_attributed(tmp_path, monkeypatch):
    runtime, first, other, local, carrier = setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, other.vault_binding_id)

    # A forged loopback forward, an API key and Tailscale identity headers are
    # dropped, and a non-JSON content type is normalised: the grant alone decides.
    response = remote.post(
        "/api/companion/capture/scoped",
        content=json.dumps({"text": "Remote boiler note"}),
        headers={
            _CRED: credential,
            "Content-Type": "text/plain",
            "X-Forwarded-For": "127.0.0.1",
            "X-API-Key": "anything",
            "Tailscale-User-Login": "owner@example.invalid",
        },
    )

    assert response.status_code == 200, response.text
    assert "Remote boiler note" in _inbox(other)
    assert "Remote boiler note" not in _inbox(first)
    receipt = response.json()["governed_write"]["authority_receipt"]
    context = receipt["active_context"]
    assert [b["vault_binding_id"] for b in context["source_bindings"]] == [other.vault_binding_id]
    assert context["selection_provenance"] == "remote_grant"
    assert context["principal_context"]["subject"] == SUBJECT_REMOTE_MCP_GRANT
    assert receipt["actor"] == "companion.capture"


def test_a_context_carrier_is_rejected_not_ignored(tmp_path, monkeypatch):
    _runtime, first, other, _local, carrier = setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, other.vault_binding_id)
    response = remote.post(
        "/api/companion/capture/scoped",
        json={"text": "Carried"},
        headers={_CRED: credential, **carrier},
    )
    assert (response.status_code, response.json()["detail"]) == (
        403,
        "remote_context_carrier_rejected",
    )
    assert "Carried" not in _inbox(first) + _inbox(other)


def test_remote_capture_cannot_name_another_binding(tmp_path, monkeypatch):
    _runtime, first, other, _local, _carrier = setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, other.vault_binding_id)

    response = remote.post(
        "/api/companion/capture/scoped",
        json={"text": "Cross vault", "target_binding_id": first.vault_binding_id},
        headers={_CRED: credential},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "remote_binding_not_granted"
    assert "Cross vault" not in _inbox(first) + _inbox(other)


@pytest.mark.parametrize(
    ("mutate", "presented", "status", "reason"),
    [
        (None, None, 401, "remote_credential_required"),
        (None, "wrong", 401, "remote_credential_invalid"),
        ("revoke", "ok", 403, "remote_grant_revoked"),
        ("expire", "ok", 403, "remote_grant_expired"),
        ("delete", "ok", 503, "remote_grant_unavailable"),
        ("corrupt", "ok", 503, "remote_grant_unavailable"),
    ],
)
def test_refused_remote_requests_never_reach_a_route(
    tmp_path, monkeypatch, mutate, presented, status, reason
):
    _runtime, first, other, _local, _carrier = setup_capture(tmp_path, monkeypatch)
    remote, path, credential = _remote(tmp_path, other.vault_binding_id)
    if mutate == "revoke":
        revoke_grant(path)
    elif mutate == "expire":
        payload = json.loads(path.read_text())
        payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(payload))
    elif mutate == "delete":
        path.unlink()
    elif mutate == "corrupt":
        path.write_text("{not json")
    headers = {} if presented is None else {_CRED: credential if presented == "ok" else presented}

    for method, route in (("GET", "/healthz"), ("POST", "/api/companion/capture/scoped")):
        response = remote.request(method, route, json={"text": "Refused"}, headers=headers)
        assert (response.status_code, response.json()["detail"]) == (status, reason)
    assert "Refused" not in _inbox(first) + _inbox(other)


def test_revocation_takes_effect_on_the_next_request(tmp_path, monkeypatch):
    setup_capture(tmp_path, monkeypatch)
    remote, path, credential = _remote(tmp_path, "any-binding")
    assert remote.get("/healthz", headers={_CRED: credential}).status_code == 200
    revoke_grant(path)
    assert remote.get("/healthz", headers={_CRED: credential}).status_code == 403


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "/search?q=boiler"),
        ("GET", "/search/scoped?q=boiler"),
        ("GET", "/api/artifacts/note?note_path=Inbox/inbox.md"),
        ("POST", "/api/companion/capture"),
        ("POST", "/api/ask"),
        ("POST", "/api/companion/active-context/selection"),
        ("GET", "/docs"),
    ],
)
def test_only_granted_routes_are_reachable(tmp_path, monkeypatch, method, route):
    setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, "any-binding")
    response = remote.request(method, route, json={"text": "x"}, headers={_CRED: credential})
    assert (response.status_code, response.json()["detail"]) == (404, "remote_route_not_granted")


def test_an_ungranted_tool_route_is_refused(tmp_path, monkeypatch):
    _runtime, first, other, _local, _carrier = setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, other.vault_binding_id, tools=("mimer.health",))
    response = remote.post(
        "/api/companion/capture/scoped", json={"text": "Not granted"}, headers={_CRED: credential}
    )
    assert response.status_code == 404
    assert "Not granted" not in _inbox(first) + _inbox(other)


def test_oversized_capture_is_refused(tmp_path, monkeypatch):
    _runtime, _first, other, _local, _carrier = setup_capture(tmp_path, monkeypatch)
    remote, _path, credential = _remote(tmp_path, other.vault_binding_id)
    response = remote.post(
        "/api/companion/capture/scoped", json={"text": "x" * 70_000}, headers={_CRED: credential}
    )
    assert response.status_code == 413


def test_loopback_gated_dependency_refuses_the_remote_subject():
    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "state": {"mimer_remote_grant": object()},
        }
    )
    with pytest.raises(HTTPException) as refused:
        require_loopback_or_api_key(request, api_key=None)
    assert refused.value.status_code == 403


def test_grant_file_lifecycle(tmp_path, capsys):
    path = tmp_path / "grant.json"
    assert (
        grant_main(
            [
                "issue",
                "--path",
                str(path),
                "--vault-binding-id",
                "b1",
                "--tool",
                "mimer.capture",
                "--days",
                "7",
            ]
        )
        == 0
    )
    issued = json.loads(capsys.readouterr().out)
    assert path.stat().st_mode & 0o077 == 0
    assert issued["credential"] not in path.read_text()
    assert admit(path, issued["credential"]).vault_binding_id == "b1"
    assert load_grant(path).tools == frozenset({"mimer.capture"})
    assert (
        grant_main(
            ["issue", "--path", str(path), "--vault-binding-id", "b1", "--tool", "mimer.ask"]
        )
        == 2
    )
    assert grant_main(["revoke", "--path", str(path)]) == 0
    with pytest.raises(GrantRefused):
        admit(path, issued["credential"])
