"""Tests for POST /api/companion/workspace/body — active note body update.

Covers:
- 200 + status=ok on successful update
- Frontmatter preserved unchanged after update
- UUID in frontmatter not modified
- 403/flow_disabled when WORKSPACE_UPDATE_FLOW_ENABLED is not set
- 403/blocked when WriteGuard is blocked
- 400 when new_body contains frontmatter
- 404 when note_path doesn't resolve
- 400 on invalid note_path (absolute, traversal)
- 422 when note_path is not a .md file (.yaml, .json, .txt, extensionless)
- rejected non-.md path does not modify any file
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
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_UPDATE_FLOW_ENABLED", "1")
    return tmp_path


@pytest.fixture()
def vault_note(vault: Path) -> Path:
    note = vault / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: note-uuid-1\ntitle: Test Note\n---\n\n# Test Note\n\nOriginal body.\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _patch_body(client: TestClient, note_path: str, new_body: str) -> dict:
    resp = client.post(
        "/api/companion/workspace/body",
        json={"note_path": note_path, "new_body": new_body},
    )
    return resp


def test_body_update_returns_ok(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(client, "notes/note.md", "# Test Note\n\nUpdated body.\n")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_body_update_writes_new_body(
    client: TestClient, vault_note: Path
) -> None:
    _patch_body(client, "notes/note.md", "# Test Note\n\nNew content here.\n")
    content = vault_note.read_text(encoding="utf-8")
    assert "New content here." in content


def test_body_update_preserves_frontmatter(
    client: TestClient, vault_note: Path
) -> None:
    _patch_body(client, "notes/note.md", "# Test Note\n\nReplaced body.\n")
    content = vault_note.read_text(encoding="utf-8")
    assert "uuid: note-uuid-1" in content
    assert "---" in content


def test_body_update_preserves_uuid(
    client: TestClient, vault_note: Path
) -> None:
    _patch_body(client, "notes/note.md", "# Renamed\n\nDifferent heading.\n")
    content = vault_note.read_text(encoding="utf-8")
    assert "note-uuid-1" in content


def test_body_update_blocked_when_flow_disabled(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKSPACE_UPDATE_FLOW_ENABLED", "0")
    resp = _patch_body(client, "notes/note.md", "# Test\n\nBody.\n")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "flow_disabled"


def test_body_update_blocked_when_flow_env_absent(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKSPACE_UPDATE_FLOW_ENABLED", raising=False)
    resp = _patch_body(client, "notes/note.md", "# Test\n\nBody.\n")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "flow_disabled"


def test_body_update_blocked_by_writeguard(
    client: TestClient, vault_note: Path
) -> None:
    import app.api.routes.companion as companion_module
    from app.write_guard import WritesBlockedError

    original = companion_module.DEFAULT_WRITE_GUARD.snapshot_fn
    companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = lambda: (_ for _ in ()).throw(
        WritesBlockedError("blocked", "test", "companion.workspace.body")
    )
    try:
        resp = _patch_body(client, "notes/note.md", "# Test\n\nBody.\n")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "writes_blocked"
    finally:
        companion_module.DEFAULT_WRITE_GUARD.snapshot_fn = original


def test_body_update_rejected_if_new_body_contains_frontmatter(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(
        client,
        "notes/note.md",
        "---\nuuid: injected\n---\n\n# Injected\n\nBody.\n",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "frontmatter_in_body"


def test_body_update_404_when_note_not_found(
    client: TestClient, vault: Path
) -> None:
    resp = _patch_body(client, "notes/nonexistent.md", "# Test\n\nBody.\n")
    assert resp.status_code == 404


def test_body_update_400_on_absolute_note_path(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(client, "/absolute/path.md", "Body.\n")
    assert resp.status_code == 400


def test_body_update_400_on_traversal_note_path(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(client, "../../../etc/passwd", "Body.\n")
    assert resp.status_code == 400


def test_body_update_response_includes_note_path(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(client, "notes/note.md", "# Test\n\nBody.\n")
    assert resp.json()["note_path"] == "notes/note.md"


def test_body_update_response_includes_content_hash(
    client: TestClient, vault_note: Path
) -> None:
    resp = _patch_body(client, "notes/note.md", "# Test\n\nUpdated.\n")
    data = resp.json()
    assert "content_hash" in data
    assert len(data["content_hash"]) > 0


# ---------------------------------------------------------------------------
# File-type restriction: only .md files allowed (P1 review gate)
# ---------------------------------------------------------------------------


def test_body_update_md_file_is_allowed(
    client: TestClient, vault_note: Path
) -> None:
    """Markdown note updates must succeed (sanity check for the allowlist)."""
    resp = _patch_body(client, "notes/note.md", "# Test Note\n\nAllowed body.\n")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_body_update_yaml_file_rejected(
    client: TestClient, vault: Path
) -> None:
    """YAML config files must be rejected with 422."""
    config_file = vault / "_system" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("key: value\n", encoding="utf-8")

    resp = _patch_body(client, "_system/settings.yaml", "injected: true\n")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "not_a_note_file"


def test_body_update_json_file_rejected(
    client: TestClient, vault: Path
) -> None:
    """JSON files must be rejected with 422."""
    json_file = vault / "data" / "index.json"
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text('{"key": "value"}\n', encoding="utf-8")

    resp = _patch_body(client, "data/index.json", '{"injected": true}')
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "not_a_note_file"


def test_body_update_txt_file_rejected(
    client: TestClient, vault: Path
) -> None:
    """Plain text files must be rejected with 422."""
    txt_file = vault / "notes" / "readme.txt"
    txt_file.parent.mkdir(parents=True, exist_ok=True)
    txt_file.write_text("Original content.\n", encoding="utf-8")

    resp = _patch_body(client, "notes/readme.txt", "Injected content.\n")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "not_a_note_file"


def test_body_update_extensionless_file_rejected(
    client: TestClient, vault: Path
) -> None:
    """Extensionless files must be rejected with 422."""
    bare_file = vault / "notes" / "noextension"
    bare_file.parent.mkdir(parents=True, exist_ok=True)
    bare_file.write_text("Original.\n", encoding="utf-8")

    resp = _patch_body(client, "notes/noextension", "Injected.\n")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "not_a_note_file"


def test_body_update_non_md_does_not_modify_file(
    client: TestClient, vault: Path
) -> None:
    """Rejected non-.md requests must not modify the file on disk."""
    config_file = vault / "config" / "app.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original_content = "safe: original\n"
    config_file.write_text(original_content, encoding="utf-8")

    _patch_body(client, "config/app.yaml", "safe: injected\n")

    assert config_file.read_text(encoding="utf-8") == original_content
