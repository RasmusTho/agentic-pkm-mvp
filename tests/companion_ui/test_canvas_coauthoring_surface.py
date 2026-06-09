"""Tests for the Canvas co-authoring surface in the Companion UI shell (#1717).

Implements CANVAS_CHAT_SURFACE/SURFACE_CANVAS_IN_COMPANION_UI (AGENTIC-CANVAS-02).

Covers:
- WorkspaceHttpClient gains coauthor() -> POST /api/canvas/sessions/{id}/coauthor
  and undo_last_edit() -> DELETE /api/canvas/sessions/{id}/edits/last.
- RealNoteWorkspaceShell exposes a canvas co-authoring region gated by the
  server-declared guards.canvas_enabled flag. Server declares, UI renders:
  the UI composes no body locally and performs no direct vault write.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

from companion_ui.workspace.real_note_workspace_shell import (
    ArtifactNotePayload,
    RealNoteWorkspaceShell,
)
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceHttpClient,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """Records httpx calls and returns canned responses without a network."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {}
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> "_FakeResponse":
        self.calls.append({"method": "POST", "url": url, "json": json})
        return _FakeResponse(self.response)

    def delete(self, url: str, *, params: Any = None, timeout: float) -> "_FakeResponse":
        self.calls.append({"method": "DELETE", "url": url, "params": params})
        return _FakeResponse(self.response)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


def _payload(
    artifact_id: str = "note-uuid-1",
    note_path: str = "notes/test.md",
    title: str = "My Test Note",
    body: str = "# My Test Note\n\nBody content here.",
    content_hash: str = "abc123",
) -> ArtifactNotePayload:
    return ArtifactNotePayload(
        artifact_id=artifact_id,
        note_path=note_path,
        title=title,
        body=body,
        content_hash=content_hash,
    )


# ---------------------------------------------------------------------------
# AC 1: HTTP client posts intent to /coauthor
# ---------------------------------------------------------------------------


def test_http_client_coauthor_posts_intent(monkeypatch) -> None:
    transport = _RecordingTransport(
        response={
            "session_id": "sess-1",
            "applied_body": "# My Test Note\n\nTightened body.",
            "change_summary": "tightened intro paragraph",
            "generated": True,
        }
    )
    monkeypatch.setattr("httpx.post", transport.post)

    client = WorkspaceHttpClient("http://localhost:18001")
    result = client.coauthor("sess-1", "tighten the intro paragraph")

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://localhost:18001/api/canvas/sessions/sess-1/coauthor"
    assert call["json"] == {"intent": "tighten the intro paragraph"}
    assert result["applied_body"] == "# My Test Note\n\nTightened body."
    assert result["change_summary"] == "tightened intro paragraph"


def test_http_client_coauthor_includes_optional_change_summary(monkeypatch) -> None:
    transport = _RecordingTransport(
        response={"session_id": "s", "applied_body": "x", "change_summary": "y", "generated": True}
    )
    monkeypatch.setattr("httpx.post", transport.post)

    client = WorkspaceHttpClient("http://localhost:18001")
    client.coauthor("sess-2", "do a thing", change_summary="explicit summary")

    assert transport.calls[0]["json"] == {
        "intent": "do a thing",
        "change_summary": "explicit summary",
    }


# ---------------------------------------------------------------------------
# AC 2: HTTP client deletes last edit for undo
# ---------------------------------------------------------------------------


def test_http_client_undo_deletes_last_edit(monkeypatch) -> None:
    transport = _RecordingTransport(
        response={
            "session_id": "sess-1",
            "ok": True,
            "undo_id": "undo-1",
            "original_edit_id": "edit-1",
        }
    )
    monkeypatch.setattr("httpx.delete", transport.delete)

    client = WorkspaceHttpClient("http://localhost:18001")
    result = client.undo_last_edit("sess-1")

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"] == "http://localhost:18001/api/canvas/sessions/sess-1/edits/last"
    assert result["ok"] is True
    assert result["undo_id"] == "undo-1"


# ---------------------------------------------------------------------------
# AC 3: shell renders intent input + applied-edit region when enabled
# ---------------------------------------------------------------------------


def test_shell_renders_canvas_region_when_enabled() -> None:
    shell = RealNoteWorkspaceShell(payload=_payload(), canvas_enabled=True)
    region = shell.canvas_region

    assert region.enabled is True
    assert region.has_intent_input is True
    assert region.has_undo_affordance is True

    # An applied edit returned by the server renders body + change summary.
    region.render_applied_edit(
        applied_body="# My Test Note\n\nTightened body.",
        change_summary="tightened intro paragraph",
    )
    assert region.applied_body == "# My Test Note\n\nTightened body."
    assert region.change_summary == "tightened intro paragraph"
    assert region.is_panel_routed is False


# ---------------------------------------------------------------------------
# AC 4: shell renders inert disabled state when flag off
# ---------------------------------------------------------------------------


def test_shell_canvas_region_disabled_when_flag_off() -> None:
    shell = RealNoteWorkspaceShell(payload=_payload(), canvas_enabled=False)
    region = shell.canvas_region

    assert region.enabled is False
    # No mutation affordances exposed in the disabled state.
    assert region.has_intent_input is False
    assert region.has_undo_affordance is False
    assert region.mutation_affordances == []


# ---------------------------------------------------------------------------
# AC 5: governance-bearing response renders as routed-to-Panel
# ---------------------------------------------------------------------------


def test_governance_bearing_response_shown_as_panel_routed() -> None:
    shell = RealNoteWorkspaceShell(payload=_payload(), canvas_enabled=True)
    region = shell.canvas_region

    # The server signals a governance-bearing mutation via HTTP 409.
    err = WorkspaceClientHTTPError(409, "governance-bearing mutation routed to Panel")
    region.handle_coauthor_error(err)

    assert region.is_panel_routed is True
    # It must NOT be presented as an applied edit.
    assert region.applied_body is None
    assert region.change_summary is None


# ---------------------------------------------------------------------------
# AC 6: no local vault write and no local body composition
# ---------------------------------------------------------------------------


def test_no_local_vault_write_or_body_composition() -> None:
    """Architecture guard: shell renders only server-applied bodies.

    The shell module must not perform direct vault I/O and must not compose
    a new body locally; it only stores what the server returned.
    """
    shell = RealNoteWorkspaceShell(payload=_payload(), canvas_enabled=True)
    region = shell.canvas_region

    server_body = "# Server-Applied\n\nOnly the server composes this."
    region.render_applied_edit(applied_body=server_body, change_summary="srv")
    # Stored verbatim — the UI did not transform or compose the body.
    assert region.applied_body == server_body

    shell_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "real_note_workspace_shell.py"
    )
    assert shell_file.exists(), f"Shell file not found: {shell_file}"

    tree = ast.parse(shell_file.read_text(encoding="utf-8"))
    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
            violations.append(f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}")

    assert not violations, (
        "real_note_workspace_shell must not perform direct vault I/O:\n"
        + "\n".join(violations)
    )
