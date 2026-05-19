"""Tests: Panel confirm response → artifact refresh (#1065).

Verifies that the workspace session model submits confirm requests, displays
typed results, and reloads the artifact payload through the read endpoint
contract — without direct vault file access.
"""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.confirm_session import (
    ArtifactPayload,
    WorkspaceConfirmSession,
)


# ---------------------------------------------------------------------------
# Stub HTTP client
# ---------------------------------------------------------------------------

_EXECUTED_CONFIRM_RESPONSE: dict[str, Any] = {
    "proposal_id": "prop-1",
    "artifact_id": "note-uuid-1",
    "status": "executed",
    "outcome": "success",
    "receipt": {"action_taken": "confirm", "outcome": "success", "timestamp": "2026-01-01T00:00:00Z"},
    "block_reason": None,
    "idempotency_key": "idem-1",
    "events_emitted": ["panel.intent.executed"],
}

_BLOCKED_CONFIRM_RESPONSE: dict[str, Any] = {
    "proposal_id": "prop-1",
    "artifact_id": "note-uuid-1",
    "status": "blocked",
    "outcome": "blocked",
    "receipt": None,
    "block_reason": {"gate": "writeguard", "message": "blocked in test"},
    "idempotency_key": "idem-1",
    "events_emitted": ["panel.action.blocked"],
}

_REJECTED_CONFIRM_RESPONSE: dict[str, Any] = {
    "proposal_id": "prop-1",
    "artifact_id": "note-uuid-1",
    "status": "rejected",
    "outcome": "rejected",
    "receipt": None,
    "block_reason": None,
    "idempotency_key": "idem-1",
    "events_emitted": [],
}

_REFRESHED_ARTIFACT: dict[str, Any] = {
    "artifact_id": "note-uuid-1",
    "note_path": "notes/test.md",
    "title": "Test Note",
    "body": "# Test Note\n\nUpdated body after confirm.",
    "content_hash": "refreshed00",
}

_REFRESHED_WORKSPACE_RESPONSE: dict[str, Any] = {
    "artifact": _REFRESHED_ARTIFACT,
    "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
    "panel": {"state": "idle", "proposal_count": 0},
    "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
}


class _StubHttpClient:
    """Stub HTTP client for testing WorkspaceConfirmSession."""

    def __init__(
        self,
        confirm_response: dict[str, Any],
        artifact_response: dict[str, Any] = _REFRESHED_WORKSPACE_RESPONSE,
    ) -> None:
        self._confirm = confirm_response
        self._artifact = artifact_response
        self.confirm_calls: list[dict] = []
        self.artifact_calls: list[dict] = []

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.confirm_calls.append({"url": url, "json": json})
        return dict(self._confirm)

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.artifact_calls.append({"url": url, "params": params})
        return dict(self._artifact)


def _confirm_kwargs(**overrides) -> dict:
    base = {
        "proposal_id": "prop-1",
        "artifact_id": "note-uuid-1",
        "note_path": "notes/test.md",
        "action": "confirm",
        "idempotency_key": "idem-1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# AC 1: UI sends confirm request, records/displays executed result
# ---------------------------------------------------------------------------


def test_panel_confirm_displays_executed_result() -> None:
    http = _StubHttpClient(confirm_response=_EXECUTED_CONFIRM_RESPONSE)
    session = WorkspaceConfirmSession(http)

    result = session.confirm(**_confirm_kwargs(action="confirm"))

    assert result.status == "executed"
    assert result.is_executed is True
    assert result.receipt is not None
    assert result.receipt["outcome"] == "success"
    assert result.receipt["action_taken"] == "confirm"
    assert session.last_result is result

    # Confirm was submitted to the right endpoint
    assert len(http.confirm_calls) == 1
    call = http.confirm_calls[0]
    assert call["url"] == "/api/panel/confirm"
    assert call["json"]["action"] == "confirm"


# ---------------------------------------------------------------------------
# AC 2: guarded (blocked) result displayed with reason, no local mutation
# ---------------------------------------------------------------------------


def test_panel_confirm_displays_guarded_result() -> None:
    http = _StubHttpClient(confirm_response=_BLOCKED_CONFIRM_RESPONSE)
    session = WorkspaceConfirmSession(http)

    result = session.confirm(**_confirm_kwargs(action="confirm"))

    assert result.status == "blocked"
    assert result.is_blocked is True
    assert result.block_reason is not None
    assert result.block_reason["gate"] == "writeguard"
    assert result.receipt is None
    # No mutation assumed — shell still loads refreshed payload from API
    assert session.current_payload is not None


# ---------------------------------------------------------------------------
# AC 3: reject result displayed as non-execution
# ---------------------------------------------------------------------------


def test_panel_confirm_displays_rejected_result() -> None:
    http = _StubHttpClient(confirm_response=_REJECTED_CONFIRM_RESPONSE)
    session = WorkspaceConfirmSession(http)

    result = session.confirm(**_confirm_kwargs(action="reject"))

    assert result.status == "rejected"
    assert result.is_rejected is True
    assert result.receipt is None
    assert result.block_reason is None
    # Confirmed call was a reject action
    assert http.confirm_calls[0]["json"]["action"] == "reject"


# ---------------------------------------------------------------------------
# AC 4: artifact payload reloaded after response via read endpoint contract
# ---------------------------------------------------------------------------


def test_panel_confirm_refreshes_artifact_payload_after_response() -> None:
    http = _StubHttpClient(
        confirm_response=_EXECUTED_CONFIRM_RESPONSE,
        artifact_response=_REFRESHED_WORKSPACE_RESPONSE,
    )
    session = WorkspaceConfirmSession(http)

    assert session.current_payload is None

    session.confirm(**_confirm_kwargs(action="confirm"))

    # Payload is refreshed after every confirm response (regardless of outcome)
    assert session.current_payload is not None
    assert isinstance(session.current_payload, ArtifactPayload)
    assert session.current_payload.content_hash == "refreshed00"
    assert session.current_payload.artifact_id == "note-uuid-1"

    # Artifact endpoint was called exactly once
    assert len(http.artifact_calls) == 1
    art_call = http.artifact_calls[0]
    assert art_call["url"] == "/api/companion/workspace"
    assert art_call["params"]["note_path"] == "notes/test.md"
    assert "artifact_id" not in art_call["params"]


# ---------------------------------------------------------------------------
# AC 5: Companion UI session has no direct vault file access
# ---------------------------------------------------------------------------


def test_panel_confirm_ui_has_no_direct_vault_file_access() -> None:
    """Architecture guard: confirm_session must not access vault files directly."""
    import ast
    import pathlib

    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    session_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "confirm_session.py"
    )
    assert session_file.exists(), f"confirm_session.py not found: {session_file}"

    tree = ast.parse(session_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
            violations.append(f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}")

    assert not violations, (
        "confirm_session must not access vault files directly:\n"
        + "\n".join(violations)
    )
