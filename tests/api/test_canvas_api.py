"""Canvas Chat session API — acceptance tests (no Postgres required)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.api.routes.artifacts import _content_hash


@pytest.fixture(autouse=True)
def _clear_sessions():
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    note = tmp_path / "note.md"
    note.write_text("---\nuuid: note-uuid-canvas\n---\n\n# Hello\n\nOriginal body.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(monkeypatch, vault: Path) -> TestClient:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    return TestClient(app)


# ---------------------------------------------------------------------------


def test_open_session_returns_session_id(client: TestClient, vault: Path) -> None:
    resp = client.post("/api/canvas/sessions", json={"note_path": "note.md", "label": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["session_id"]


def test_edit_updates_vault_file(client: TestClient, vault: Path) -> None:
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "edit-test"}
    )
    session_id = open_resp.json()["session_id"]

    edit_resp = client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={
            "new_body": "Updated body.",
            "change_summary": "rewrote",
            "content_hash": _content_hash((vault / "note.md").read_text(encoding="utf-8")),
        },
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["ok"] is True
    note = vault / "note.md"
    assert "Updated body." in note.read_text(encoding="utf-8")


def test_undo_last_edit_reverts_body_and_preserves_log(client: TestClient, vault: Path) -> None:
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "undo-test"}
    )
    session_id = open_resp.json()["session_id"]
    log_path = Path(open_resp.json()["log_path"])

    edit_resp = client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={
            "new_body": "Updated body.",
            "change_summary": "rewrote",
            "content_hash": _content_hash((vault / "note.md").read_text(encoding="utf-8")),
        },
    )
    assert edit_resp.status_code == 200

    undo_resp = client.delete(f"/api/canvas/sessions/{session_id}/edits/last")

    assert undo_resp.status_code == 200
    assert undo_resp.json()["ok"] is True
    assert "Original body." in (vault / "note.md").read_text(encoding="utf-8")
    log_content = log_path.read_text(encoding="utf-8")
    assert "rewrote" in log_content
    assert "[undo:" in log_content
    assert "reverted edit:" in log_content


def test_undo_rejects_diverged_body(client: TestClient, vault: Path) -> None:
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "undo-conflict"}
    )
    session_id = open_resp.json()["session_id"]
    client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={
            "new_body": "Updated body.",
            "change_summary": "rewrote",
            "content_hash": _content_hash((vault / "note.md").read_text(encoding="utf-8")),
        },
    )
    (vault / "note.md").write_text("# Hello\n\nManual user change.\n", encoding="utf-8")

    undo_resp = client.delete(f"/api/canvas/sessions/{session_id}/edits/last")

    assert undo_resp.status_code == 409
    assert "Manual user change." in (vault / "note.md").read_text(encoding="utf-8")


def test_edit_rejects_stale_content_hash(client: TestClient, vault: Path) -> None:
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "stale-test"}
    )
    session_id = open_resp.json()["session_id"]

    edit_resp = client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={
            "new_body": "Updated body.",
            "change_summary": "rewrote",
            "content_hash": "stale-hash",
        },
    )

    assert edit_resp.status_code == 409
    assert "Original body." in (vault / "note.md").read_text(encoding="utf-8")


def test_close_session_writes_log(client: TestClient, vault: Path) -> None:
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "close-test"}
    )
    data = open_resp.json()
    session_id = data["session_id"]
    log_path = Path(data["log_path"])

    close_resp = client.delete(f"/api/canvas/sessions/{session_id}")
    assert close_resp.status_code == 200
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "close-test" in content or "closed" in content


def test_governance_action_creates_intent_not_note_edit(client: TestClient, vault: Path) -> None:
    note = vault / "note.md"
    original = note.read_text(encoding="utf-8")
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "gov-test"}
    )
    session_id = open_resp.json()["session_id"]

    gov_resp = client.post(
        f"/api/canvas/sessions/{session_id}/governance",
        json={"action_type": "frontmatter_update", "payload": {"tag": "approved"}},
    )
    assert gov_resp.status_code == 200
    body = gov_resp.json()
    assert "intent_id" in body
    assert body["intent_id"]
    # Note file must NOT have been modified by the governance route
    assert note.read_text(encoding="utf-8") == original


def test_governance_action_stages_panel_proposal(client: TestClient, vault: Path) -> None:
    confirm_module._proposal_store.clear()
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "gov-stage-test"}
    )
    session_id = open_resp.json()["session_id"]

    gov_resp = client.post(
        f"/api/canvas/sessions/{session_id}/governance",
        json={"action_type": "frontmatter_update", "payload": {"field": "maturity", "value": "evergreen"}},
    )
    assert gov_resp.status_code == 200
    body = gov_resp.json()
    intent_id = body["intent_id"]
    artifact_id = body["artifact_id"]

    # Proposal must be staged under intent_id, retrievable by Panel confirm service
    staged = confirm_module._proposal_store.get(intent_id)
    assert staged is not None
    assert staged.artifact_id == artifact_id
    assert artifact_id == "note-uuid-canvas"
    assert staged.intent_event.payload.note.uuid == "note-uuid-canvas"
    assert staged.intent_event.payload.note.path == "note.md"
    assert staged.intent_event.payload.actions[0].mapping.params["field"] == "maturity"


def test_canvas_governance_proposal_uses_workspace_artifact_uuid(client: TestClient, vault: Path) -> None:
    confirm_module._proposal_store.clear()
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "gov-identity-test"}
    )
    session_id = open_resp.json()["session_id"]

    gov_resp = client.post(
        f"/api/canvas/sessions/{session_id}/governance",
        json={"action_type": "frontmatter_update", "payload": {"field": "maturity", "value": "evergreen"}},
    )

    assert gov_resp.status_code == 200
    artifact_id = gov_resp.json()["artifact_id"]
    assert artifact_id == "note-uuid-canvas"
    staged = confirm_module._proposal_store.get(gov_resp.json()["intent_id"])
    assert staged is not None
    assert staged.artifact_id == artifact_id


def test_canvas_disabled_returns_403(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)
    resp = client.post("/api/canvas/sessions", json={"note_path": "note.md", "label": "x"})
    assert resp.status_code == 403
