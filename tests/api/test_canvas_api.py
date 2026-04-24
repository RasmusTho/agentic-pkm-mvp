"""Canvas Chat session API — acceptance tests (no Postgres required)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
from app.api.app import app


@pytest.fixture(autouse=True)
def _clear_sessions():
    canvas_module._sessions.clear()
    yield
    canvas_module._sessions.clear()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    note = tmp_path / "note.md"
    note.write_text("# Hello\n\nOriginal body.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(monkeypatch, vault: Path) -> TestClient:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    return TestClient(app)


# ---------------------------------------------------------------------------


def test_open_session_returns_session_id(client: TestClient, vault: Path) -> None:
    note = vault / "note.md"
    resp = client.post("/api/canvas/sessions", json={"note_path": str(note), "label": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["session_id"]


def test_edit_updates_vault_file(client: TestClient, vault: Path) -> None:
    note = vault / "note.md"
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": str(note), "label": "edit-test"}
    )
    session_id = open_resp.json()["session_id"]

    edit_resp = client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={"new_body": "Updated body.", "change_summary": "rewrote"},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["ok"] is True
    assert "Updated body." in note.read_text(encoding="utf-8")


def test_close_session_writes_log(client: TestClient, vault: Path) -> None:
    note = vault / "note.md"
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": str(note), "label": "close-test"}
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
        "/api/canvas/sessions", json={"note_path": str(note), "label": "gov-test"}
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


def test_canvas_disabled_returns_403(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)
    note = vault / "note.md"
    resp = client.post("/api/canvas/sessions", json={"note_path": str(note), "label": "x"})
    assert resp.status_code == 403
