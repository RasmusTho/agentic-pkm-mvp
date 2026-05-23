"""Tests for workspace update flow configuration in the companion workspace API.

Covers:
- update_flow_available field present in guards response
- False when COMPANION_WORKSPACE_UPDATE_ENABLED is not set
- False when COMPANION_WORKSPACE_UPDATE_ENABLED=0
- True when COMPANION_WORKSPACE_UPDATE_ENABLED=1 and WriteGuard ok
- False when WriteGuard is blocked even if flag is set
- Governance actions (panel) remain unaffected by this flag
- update_flow_available is distinct from canvas_enabled
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.app import app


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


@pytest.fixture()
def vault_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    note = tmp_path / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: note-uuid-1\n---\n\n# Test Note\n\nBody text.\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _workspace(client: TestClient) -> dict:
    resp = client.get("/api/companion/workspace", params={"note_path": "notes/note.md"})
    assert resp.status_code == 200
    return resp.json()


def test_update_flow_available_field_present(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COMPANION_WORKSPACE_UPDATE_ENABLED", raising=False)
    data = _workspace(client)
    assert "update_flow_available" in data["guards"]


def test_update_flow_disabled_by_default(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COMPANION_WORKSPACE_UPDATE_ENABLED", raising=False)
    data = _workspace(client)
    assert data["guards"]["update_flow_available"] is False


def test_update_flow_disabled_when_explicitly_zero(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "0")
    data = _workspace(client)
    assert data["guards"]["update_flow_available"] is False


def test_update_flow_available_when_flag_set_and_writeguard_ok(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "1")
    data = _workspace(client)
    # WriteGuard is ok in test env by default
    assert data["guards"]["writeguard_status"] == "ok"
    assert data["guards"]["update_flow_available"] is True


def test_update_flow_unavailable_when_writeguard_blocked(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.routes.companion as companion_module
    from app.write_guard import WritesBlockedError

    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "1")
    original = companion_module.DEFAULT_WRITE_GUARD.snapshot_fn
    companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = lambda: (_ for _ in ()).throw(
        WritesBlockedError("blocked in test")
    )
    try:
        data = _workspace(client)
        assert data["guards"]["update_flow_available"] is False
    finally:
        companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = original


def test_update_flow_independent_of_canvas_enabled(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # canvas_enabled=True but workspace update capability can still be disabled by config
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "0")
    data = _workspace(client)
    assert data["guards"]["canvas_enabled"] is True
    assert data["guards"]["update_flow_available"] is False


def test_update_flow_does_not_affect_panel_state(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COMPANION_WORKSPACE_UPDATE_ENABLED", raising=False)
    data = _workspace(client)
    # Panel governance is always present regardless of update flow flag
    assert "state" in data["panel"]
    assert data["panel"]["state"] in {"idle", "proposals-staged", "blocked", "receipt-displayed"}
