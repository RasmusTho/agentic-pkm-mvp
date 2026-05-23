"""Companion workspace active-note body update API tests (#1226)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_guard_snapshot() -> None:
    yield
    companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = DEFAULT_WRITE_GUARD.snapshot_fn


@pytest.fixture()
def workspace_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("COMPANION_WORKSPACE_UPDATE_ENABLED", "1")

    active = tmp_path / "notes" / "active.md"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(
        "---\n"
        "uuid: active-uuid-1\n"
        "title: Active\n"
        "---\n\n"
        "# Active\n\n"
        "Initial active body.\n",
        encoding="utf-8",
    )

    other = tmp_path / "notes" / "other.md"
    other.write_text(
        "---\n"
        "uuid: other-uuid-1\n"
        "---\n\n"
        "# Other\n\n"
        "Other note body.\n",
        encoding="utf-8",
    )

    return {"active": active, "other": other}


def _workspace(client: TestClient, note_path: str) -> dict:
    resp = client.get("/api/companion/workspace", params={"note_path": note_path})
    assert resp.status_code == 200
    return resp.json()


def test_body_update_is_scoped_to_active_note(
    client: TestClient,
    workspace_notes: dict[str, Path],
) -> None:
    workspace = _workspace(client, "notes/active.md")
    content_hash = workspace["artifact"]["content_hash"]

    resp = client.post(
        "/api/companion/workspace/update",
        json={
            "active_note_path": "notes/active.md",
            "target_note_path": "notes/other.md",
            "new_body": "# Should not apply\n\nNope.\n",
            "content_hash": content_hash,
        },
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "active_note_scope_mismatch"
    assert detail["state"] == "blocked"
    assert "active note only" in detail["message"].lower()

    assert "Initial active body." in workspace_notes["active"].read_text(encoding="utf-8")
    assert "Other note body." in workspace_notes["other"].read_text(encoding="utf-8")


def test_body_update_preserves_frontmatter_and_uuid(
    client: TestClient,
    workspace_notes: dict[str, Path],
) -> None:
    workspace = _workspace(client, "notes/active.md")
    content_hash = workspace["artifact"]["content_hash"]

    resp = client.post(
        "/api/companion/workspace/update",
        json={
            "active_note_path": "notes/active.md",
            "target_note_path": "notes/active.md",
            "new_body": "# Active\n\nUpdated body from Companion workspace.\n",
            "content_hash": content_hash,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["state"] == "success"
    assert payload["note_path"] == "notes/active.md"

    updated = workspace_notes["active"].read_text(encoding="utf-8")
    assert "uuid: active-uuid-1" in updated
    assert "title: Active" in updated
    assert "Updated body from Companion workspace." in updated
    assert "Initial active body." not in updated


def test_body_update_respects_write_guard(
    client: TestClient,
    workspace_notes: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(client, "notes/active.md")
    content_hash = workspace["artifact"]["content_hash"]
    mock_guard = MagicMock(spec=WriteGuard)
    mock_guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked",
        "write guard active",
        "companion.workspace.update.active_note_body",
    )
    monkeypatch.setattr(companion_module, "DEFAULT_WRITE_GUARD", mock_guard)

    resp = client.post(
        "/api/companion/workspace/update",
        json={
            "active_note_path": "notes/active.md",
            "target_note_path": "notes/active.md",
            "new_body": "# Active\n\nBlocked edit.\n",
            "content_hash": content_hash,
        },
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "writeguard_blocked"
    assert detail["state"] == "blocked"
    assert "blocked" in detail["message"].lower()
    assert "Initial active body." in workspace_notes["active"].read_text(encoding="utf-8")
