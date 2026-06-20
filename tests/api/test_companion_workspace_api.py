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
from tests.api._vault_test_helpers import bind_initialized_vault, bind_selected_vault


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
    bind_selected_vault(monkeypatch, tmp_path)
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
    assert data["artifact"]["artifact_kind"] == "human_note"
    assert data["artifact"]["identity_source"] == "frontmatter.uuid"
    assert data["artifact"]["identity_state"] == "resolved"


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


def test_workspace_panel_state_exposes_source_backed_selectable_options(
    client: TestClient,
    vault_note: Path,
) -> None:
    vault_note.write_text(
        "---\n"
        "uuid: note-uuid-1\n"
        "---\n\n"
        "# Test Note\n\n"
        "- [ ] ordinary task\n\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Do the thing.\n"
        "## AI-åtgärder\n"
        "- [ ] Send email <!--ai:option_id=opt_workspace--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
        "%% AI:End %%\n",
        encoding="utf-8",
    )

    resp = _workspace(client)

    assert resp.status_code == 200
    data = resp.json()
    panel = data["panel"]
    assert panel["state"] == "proposals-staged"
    assert panel["proposal_count"] == 1
    options = panel["selectable_options"]
    assert len(options) == 1
    assert options[0]["option_id"] == "opt_workspace"
    assert options[0]["content_hash"] == data["artifact"]["content_hash"]
    assert options[0]["selectable"] is True


def test_workspace_artifact_id_uses_frontmatter_uuid(client: TestClient, vault_note: Path) -> None:
    resp = _workspace(client)

    assert resp.status_code == 200
    artifact = resp.json()["artifact"]
    assert artifact["artifact_id"] == "note-uuid-1"
    assert artifact["identity_source"] == "frontmatter.uuid"
    assert artifact["identity_state"] == "resolved"


def test_workspace_missing_uuid_heals_eligible_note_without_hash_identity(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "notes" / "uuidless.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: UUIDless\n---\n\n# UUIDless\n\nBody.\n", encoding="utf-8")
    bind_initialized_vault(monkeypatch, tmp_path)

    resp = _workspace(client, "notes/uuidless.md")

    assert resp.status_code == 200
    artifact = resp.json()["artifact"]
    assert artifact["artifact_id"]
    assert artifact["artifact_id"] != companion_module._content_hash("notes/uuidless.md")
    assert artifact["identity_source"] == "uuid_healing"
    assert artifact["identity_state"] == "healed"
    assert f"uuid: {artifact['artifact_id']}" in note.read_text(encoding="utf-8")


def test_workspace_missing_uuid_unresolved_state_has_no_hash_artifact_id(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "notes" / "blocked.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Blocked\n\nBody.\n", encoding="utf-8")
    bind_selected_vault(monkeypatch, tmp_path)

    def _blocked(_path: Path, *, vault_root: Path) -> str:
        raise WritesBlockedError("blocked", "write guard active", "ensure uuid")

    monkeypatch.setattr(companion_module, "ensure_note_uuid", _blocked, raising=False)
    monkeypatch.setattr("app.services.artifact_identity.ensure_note_uuid", _blocked)

    resp = _workspace(client, "notes/blocked.md")

    assert resp.status_code == 200
    artifact = resp.json()["artifact"]
    assert artifact["artifact_id"] is None
    assert artifact["identity_source"] == "missing"
    assert artifact["identity_state"] == "unresolved_missing_uuid"
    assert artifact["artifact_id"] != companion_module._content_hash("notes/blocked.md")


def test_workspace_companion_note_has_no_path_hash_identity(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_uuid = "note-uuid-1"
    companion = tmp_path / "⚙️ System" / "companions" / f"{note_uuid}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text(
        "---\n"
        f"uuid: {note_uuid}\n"
        "source_ref: notes/note.md\n"
        "content_hash: abc123\n"
        "---\n",
        encoding="utf-8",
    )
    bind_selected_vault(monkeypatch, tmp_path)

    resp = _workspace(client, f"⚙️ System/companions/{note_uuid}.md")

    assert resp.status_code == 200
    artifact = resp.json()["artifact"]
    assert artifact["artifact_id"] == f"companion:{note_uuid}"
    assert artifact["artifact_kind"] == "companion_note"
    assert artifact["identity_source"] == "companion_path"
    assert artifact["identity_state"] == "companion_of_resolved"
    assert artifact["companion_of"] == note_uuid
    assert artifact["owns_identity"] is False


def test_workspace_legacy_companion_note_has_companion_identity(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_uuid = "legacy-note-uuid-1"
    companion = tmp_path / "_system" / "companions" / f"{note_uuid}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text(
        "---\n"
        f"uuid: {note_uuid}\n"
        "source_ref: notes/note.md\n"
        "content_hash: abc123\n"
        "---\n",
        encoding="utf-8",
    )
    bind_selected_vault(monkeypatch, tmp_path)

    resp = _workspace(client, f"_system/companions/{note_uuid}.md")

    assert resp.status_code == 200
    artifact = resp.json()["artifact"]
    assert artifact["artifact_id"] == f"companion:{note_uuid}"
    assert artifact["artifact_kind"] == "companion_note"
    assert artifact["identity_source"] == "companion_path"
    assert artifact["identity_state"] == "companion_of_resolved"
    assert artifact["companion_of"] == note_uuid
    assert artifact["owns_identity"] is False


def test_workspace_panel_counts_canvas_origin_proposals_by_uuid(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    note = tmp_path / "notes" / "canvas.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: note-uuid-canvas-workspace\n---\n\n# Canvas\n\nBody.\n",
        encoding="utf-8",
    )
    bind_selected_vault(monkeypatch, tmp_path)

    open_resp = client.post(
        "/api/canvas/sessions",
        json={"note_path": "notes/canvas.md", "label": "workspace-panel-count"},
    )
    session_id = open_resp.json()["session_id"]
    gov_resp = client.post(
        f"/api/canvas/sessions/{session_id}/governance",
        json={"action_type": "frontmatter_update", "payload": {"field": "maturity", "value": "evergreen"}},
    )

    assert gov_resp.status_code == 200
    assert gov_resp.json()["artifact_id"] == "note-uuid-canvas-workspace"

    resp = _workspace(client, "notes/canvas.md")

    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact"]["artifact_id"] == "note-uuid-canvas-workspace"
    assert data["panel"]["state"] == "proposals-staged"
    assert data["panel"]["proposal_count"] == 1


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


def test_workspace_update_capability_exposed_for_dev_config(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "1")

    resp = _workspace(client)

    assert resp.status_code == 200
    workspace_update = resp.json()["guards"]["workspace_update"]
    assert workspace_update["available"] is True
    assert workspace_update["state"] == "available"
    assert workspace_update["reason"] == "explicit_dev_config"
    assert workspace_update["scope"] == "active_note_body"
    assert workspace_update["config_mode"] == "explicit"


def test_workspace_update_capability_does_not_enable_governance_actions(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "1")

    resp = _workspace(client)

    assert resp.status_code == 200
    workspace_update = resp.json()["guards"]["workspace_update"]
    assert workspace_update["governance_actions_enabled"] is False
    assert workspace_update["scope"] == "active_note_body"


def test_workspace_note_not_found(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)

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
