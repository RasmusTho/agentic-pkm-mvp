"""Companion workspace aggregate endpoint tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.chat.session_log import SessionLog
from app.events.panel import NoteRef, PanelInfo, PanelIntentEvent, PanelIntentPayload
from app.panel.confirmation import StagedProposal
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError


@pytest.fixture(autouse=True)
def _clear_runtime_state() -> None:
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = DEFAULT_WRITE_GUARD.snapshot_fn


@pytest.fixture()
def vault_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    note = tmp_path / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        "uuid: note-uuid-1\n"
        "---\n\n"
        "# Test Note\n\n"
        "Body text.\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _workspace(client: TestClient, note_path: str = "notes/note.md"):
    return client.get("/api/companion/workspace", params={"note_path": note_path})


def _artifact_id(client: TestClient) -> str:
    return _workspace(client).json()["artifact"]["artifact_id"]


def _stage_panel_proposal(artifact_id: str) -> None:
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=artifact_id, path="notes/note.md"),
            panel=PanelInfo(panel_id="proposal-1", instruction="do the thing"),
        )
    )
    confirm_module._proposal_store.stage(
        "proposal-1",
        StagedProposal(
            artifact_id=artifact_id,
            intent_event=intent,
            proposed_at=0.0,
        ),
    )


def test_workspace_returns_artifact_payload(client: TestClient, vault_note: Path) -> None:
    resp = _workspace(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact"]["note_path"] == "notes/note.md"
    assert data["artifact"]["title"] == "Test Note"
    assert "Body text." in data["artifact"]["body"]
    assert data["artifact"]["content_hash"]
    assert data["artifact"]["artifact_id"] == "note-uuid-1"


def test_workspace_canvas_state_no_session(client: TestClient, vault_note: Path) -> None:
    resp = _workspace(client)

    assert resp.status_code == 200
    canvas = resp.json()["canvas"]
    assert canvas["session_id"] is None
    assert canvas["session_state"] is None
    assert canvas["session_persistence"] == "in_memory"
    assert canvas["undo_available"] is False
    assert canvas["applied_edit_count"] == 0
    assert canvas["undone_edit_count"] == 0


def test_workspace_canvas_state_with_open_session(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    log_path = tmp_path / ".chats" / "note" / "session.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("session", encoding="utf-8")
    canvas_module._sessions["session-1"] = SessionLog(
        log_path=log_path,
        session_id="session-1",
        note_path=vault_note,
        label="test",
    )
    canvas_module._edit_history["session-1"] = [
        canvas_module._AppliedBodyEdit(
            edit_id="edit-1",
            body_before="Body text.\n",
            body_after=canvas_module._note_body(vault_note),
            change_summary="updated",
        )
    ]
    canvas_module._undone_history["session-1"] = []

    resp = _workspace(client)

    assert resp.status_code == 200
    canvas = resp.json()["canvas"]
    assert canvas["session_id"] == "session-1"
    assert canvas["session_state"] == "active"
    assert canvas["session_log_path"] == ".chats/note/session.md"
    assert canvas["undo_available"] is True
    assert canvas["applied_edit_count"] == 1
    assert canvas["undone_edit_count"] == 0
    assert canvas["session_persistence"] == "in_memory"


def test_workspace_undo_unavailable_when_note_body_diverged(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    log_path = tmp_path / ".chats" / "note" / "session.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("session", encoding="utf-8")
    canvas_module._sessions["session-1"] = SessionLog(
        log_path=log_path,
        session_id="session-1",
        note_path=vault_note,
        label="test",
    )
    canvas_module._edit_history["session-1"] = [
        canvas_module._AppliedBodyEdit(
            edit_id="edit-1",
            body_before="Body text.\n",
            body_after="Updated body.\n",
            change_summary="updated",
        )
    ]

    resp = _workspace(client)

    assert resp.status_code == 200
    canvas = resp.json()["canvas"]
    assert canvas["applied_edit_count"] == 1
    assert canvas["undo_available"] is False


def test_workspace_panel_state(client: TestClient, vault_note: Path) -> None:
    artifact_id = _artifact_id(client)
    _stage_panel_proposal(artifact_id)

    resp = _workspace(client)

    assert resp.status_code == 200
    panel = resp.json()["panel"]
    assert panel["state"] == "proposals-staged"
    assert panel["proposal_count"] == 1
    assert panel["receipt_count"] == 0
    assert panel["blocked_reason"] is None


def test_workspace_guards(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    mock_guard = MagicMock(spec=WriteGuard)
    mock_guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked", "guard active", "companion.workspace.read"
    )
    monkeypatch.setattr(companion_module, "DEFAULT_WRITE_GUARD", mock_guard)

    resp = _workspace(client)

    assert resp.status_code == 200
    guards = resp.json()["guards"]
    assert guards["canvas_enabled"] is True
    assert guards["writeguard_status"] == "blocked"


def test_workspace_note_not_found(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))

    resp = _workspace(client, "missing.md")

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error"] == "note_not_found"
    assert detail["note_path"] == "missing.md"
    assert detail["trace_id"]


def test_workspace_no_vault_paths_in_response(client: TestClient, vault_note: Path, tmp_path: Path) -> None:
    canvas_module._sessions["session-1"] = SessionLog(
        log_path=tmp_path / ".chats" / "note" / "session.md",
        session_id="session-1",
        note_path=vault_note,
        label="test",
    )

    resp = _workspace(client)

    assert resp.status_code == 200
    payload = resp.text
    assert str(tmp_path) not in payload
    assert str(vault_note) not in payload
