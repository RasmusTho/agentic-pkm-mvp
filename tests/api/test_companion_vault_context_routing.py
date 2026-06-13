from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _write_note(vault_root: Path, rel_path: str, body: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _fresh_manager_with_persisted_active_vault(tmp_path: Path, selected_vault: Path) -> VaultManager:
    app_local_path = tmp_path / "app-local.md"
    persisted_manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    result = persisted_manager.initialize_vault(
        selected_vault,
        vault_name="Selected Vault",
        machine_role="testNode",
        remember=True,
    )
    assert result.context.status == "selected"

    fresh_manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    assert fresh_manager.context.status == "none"
    return fresh_manager


def test_data_endpoints_use_persisted_last_active_before_context_call(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_vault = tmp_path / "env-vault"
    selected_vault = tmp_path / "selected-vault"
    _write_note(env_vault, "notes/env-only.md", "# Env Only\n\nWrong vault.\n")
    _write_note(selected_vault, "notes/selected-only.md", "# Selected Only\n\nRight vault.\n")
    monkeypatch.setenv("VAULT_ROOT", str(env_vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    fresh_manager = _fresh_manager_with_persisted_active_vault(tmp_path, selected_vault)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: fresh_manager)

    selected_resp = client.get("/api/companion/vault/notes", params={"q": "selected-only"})
    assert selected_resp.status_code == 200
    assert [note["path"] for note in selected_resp.json()["notes"]] == ["notes/selected-only.md"]

    env_resp = client.get("/api/companion/vault/notes", params={"q": "env-only"})
    assert env_resp.status_code == 200
    assert env_resp.json()["notes"] == []
    assert fresh_manager.context.status == "selected"
    assert fresh_manager.context.active_vault_path == str(selected_vault)


def test_save_note_body_targets_persisted_vault(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_vault = tmp_path / "env-vault"
    selected_vault = tmp_path / "selected-vault"
    env_note = _write_note(env_vault, "notes/shared.md", "# Shared\n\nEnv body.\n")
    selected_note = _write_note(selected_vault, "notes/shared.md", "# Shared\n\nSelected body.\n")
    monkeypatch.setenv("VAULT_ROOT", str(env_vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    fresh_manager = _fresh_manager_with_persisted_active_vault(tmp_path, selected_vault)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: fresh_manager)

    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "notes/shared.md", "new_body": "# Shared\n\nUpdated selected body.\n"},
    )

    assert resp.status_code == 200
    assert "Updated selected body." in selected_note.read_text(encoding="utf-8")
    assert env_note.read_text(encoding="utf-8") == "# Shared\n\nEnv body.\n"
    assert fresh_manager.context.status == "selected"
    assert fresh_manager.context.active_vault_path == str(selected_vault)
