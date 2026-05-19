"""Tests: live workspace HTTP client (#1071).

Verifies that WorkspaceHttpClient:
- fetches workspace aggregate payloads from a configured base URL
- submits Panel confirm requests to the correct endpoint
- maps executed/blocked/rejected/logged outcomes into WorkspaceConfirmSession shape
- surfaces HTTP/API failures as typed client errors, not silent empty states
- has no direct vault file access
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import httpx as _httpx
import pytest

from companion_ui.workspace.confirm_session import WorkspaceConfirmSession
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceClientNetworkError,
    WorkspaceHttpClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, payload: Any) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    if isinstance(payload, str):
        m.text = payload
        m.json.return_value = {}
    else:
        m.text = str(payload)
        m.json.return_value = payload
    return m


_SAMPLE_ARTIFACT: dict[str, Any] = {
    "artifact_id": "note-uuid-1",
    "note_path": "/vault/notes/test.md",
    "title": "Test Note",
    "body": "# Test Note\n\nBody content.",
    "content_hash": "abc123def456",
}

_REFRESHED_ARTIFACT: dict[str, Any] = {
    "artifact_id": "note-uuid-1",
    "note_path": "/vault/notes/test.md",
    "title": "Test Note",
    "body": "# Test Note\n\nUpdated body after confirm.",
    "content_hash": "refreshed00",
}

_REFRESHED_WORKSPACE: dict[str, Any] = {
    "artifact": _REFRESHED_ARTIFACT,
    "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
    "panel": {"state": "idle", "proposal_count": 0},
    "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
}


# ---------------------------------------------------------------------------
# AC 1: client fetches artifact note payload from configured base URL
# ---------------------------------------------------------------------------


def test_workspace_http_client_fetches_workspace_aggregate() -> None:
    """Client calls GET /api/companion/workspace at the configured base URL."""
    mock_resp = _mock_response(200, {"artifact": _SAMPLE_ARTIFACT})

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        result = client.get(
            "/api/companion/workspace",
            params={"note_path": "/vault/notes/test.md"},
        )

    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert call_args.args[0] == "http://localhost:18001/api/companion/workspace"
    assert call_args.kwargs["params"]["note_path"] == "/vault/notes/test.md"

    assert result["artifact"]["artifact_id"] == "note-uuid-1"
    assert result["artifact"]["title"] == "Test Note"
    assert result["artifact"]["content_hash"] == "abc123def456"
    assert "Body content" in result["artifact"]["body"]


# ---------------------------------------------------------------------------
# AC 2: client submits Panel confirm request
# ---------------------------------------------------------------------------


def test_workspace_http_client_submits_panel_confirm() -> None:
    """Client calls POST /api/panel/confirm at the configured base URL."""
    confirm_payload: dict[str, Any] = {
        "proposal_id": "prop-1",
        "artifact_id": "note-uuid-1",
        "status": "executed",
        "receipt": {"action_taken": "confirm", "outcome": "success"},
        "block_reason": None,
        "events_emitted": ["panel.intent.executed"],
    }
    mock_resp = _mock_response(200, confirm_payload)

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        result = client.post(
            "/api/panel/confirm",
            json={
                "proposal_id": "prop-1",
                "artifact_id": "note-uuid-1",
                "action": "confirm",
                "idempotency_key": "idem-1",
            },
        )

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "http://localhost:18001/api/panel/confirm"
    assert call_args.kwargs["json"]["proposal_id"] == "prop-1"
    assert call_args.kwargs["json"]["action"] == "confirm"

    assert result["status"] == "executed"
    assert result["receipt"]["outcome"] == "success"


# ---------------------------------------------------------------------------
# AC 3: client maps confirm outcomes into WorkspaceConfirmSession shape
# ---------------------------------------------------------------------------


_OUTCOME_FIXTURES: list[tuple[str, dict[str, Any]]] = [
    (
        "executed",
        {
            "receipt": {"action_taken": "confirm", "outcome": "success", "timestamp": "2026-01-01T00:00:00Z"},
            "block_reason": None,
            "events_emitted": ["panel.intent.executed"],
        },
    ),
    (
        "blocked",
        {
            "receipt": None,
            "block_reason": {"gate": "writeguard", "message": "blocked in test"},
            "events_emitted": ["panel.action.blocked"],
        },
    ),
    (
        "rejected",
        {
            "receipt": None,
            "block_reason": None,
            "events_emitted": [],
        },
    ),
    (
        "logged",
        {
            "receipt": None,
            "block_reason": None,
            "events_emitted": ["panel.action.logged"],
        },
    ),
]


def test_workspace_http_client_maps_panel_confirm_outcomes() -> None:
    """Client maps executed/blocked/rejected/logged responses into WorkspaceConfirmSession shape."""
    for status, extra in _OUTCOME_FIXTURES:
        confirm_payload: dict[str, Any] = {
            "proposal_id": "prop-1",
            "artifact_id": "note-uuid-1",
            "status": status,
            **extra,
        }
        confirm_mock = _mock_response(200, confirm_payload)
        artifact_mock = _mock_response(200, _REFRESHED_WORKSPACE)

        with patch("httpx.post", return_value=confirm_mock), \
             patch("httpx.get", return_value=artifact_mock):
            client = WorkspaceHttpClient(base_url="http://localhost:18001")
            session = WorkspaceConfirmSession(client)
            outcome = session.confirm(
                proposal_id="prop-1",
                artifact_id="note-uuid-1",
                note_path="/vault/notes/test.md",
                action="confirm",
                idempotency_key="idem-1",
            )

        assert outcome.status == status, f"Expected status {status!r}, got {outcome.status!r}"

        if status == "executed":
            assert outcome.is_executed is True
            assert outcome.receipt is not None
        elif status == "blocked":
            assert outcome.is_blocked is True
            assert outcome.block_gate == "writeguard"
        elif status == "rejected":
            assert outcome.is_rejected is True
        elif status == "logged":
            assert outcome.status == "logged"

        # Payload always refreshed after confirm
        assert session.current_payload is not None
        assert session.current_payload.content_hash == "refreshed00"


# ---------------------------------------------------------------------------
# AC 4: HTTP/API failures surfaced as typed client errors
# ---------------------------------------------------------------------------


def test_workspace_http_client_surfaces_typed_errors() -> None:
    """HTTP and network failures surface as typed errors, not silent empty states."""
    # 404 → WorkspaceClientHTTPError with status_code
    with patch("httpx.get", return_value=_mock_response(404, '{"error":"note_not_found"}')):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientHTTPError) as exc_info:
            client.get("/api/companion/workspace", params={"note_path": "missing.md"})
        assert exc_info.value.status_code == 404

    # 500 → WorkspaceClientHTTPError with status_code
    with patch("httpx.get", return_value=_mock_response(500, "Internal Server Error")):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientHTTPError) as exc_info:
            client.get("/api/companion/workspace", params={"note_path": "error.md"})
        assert exc_info.value.status_code == 500

    # 422 on confirm → WorkspaceClientHTTPError
    with patch("httpx.post", return_value=_mock_response(422, '{"detail":"same-turn execution"}')):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientHTTPError) as exc_info:
            client.post("/api/panel/confirm", json={"action": "confirm"})
        assert exc_info.value.status_code == 422

    # Network error → WorkspaceClientNetworkError (never silent)
    with patch("httpx.get", side_effect=_httpx.ConnectError("connection refused")):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientNetworkError):
            client.get("/api/companion/workspace", params={"note_path": "test.md"})

    # Timeout → WorkspaceClientNetworkError
    with patch("httpx.get", side_effect=_httpx.TimeoutException("timed out")):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientNetworkError):
            client.get("/api/companion/workspace", params={"note_path": "slow.md"})


# ---------------------------------------------------------------------------
# AC 5: client has no direct vault file access
# ---------------------------------------------------------------------------


def test_workspace_http_client_has_no_direct_vault_file_access() -> None:
    """Architecture guard: workspace HTTP client must not access vault files directly."""
    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    client_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "workspace_http_client.py"
    )
    assert client_file.exists(), f"workspace_http_client.py not found: {client_file}"

    tree = ast.parse(client_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
            violations.append(f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}")

    assert not violations, (
        "workspace_http_client must not access vault files directly:\n"
        + "\n".join(violations)
    )
