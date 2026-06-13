from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import companion as companion_module
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import MachineRole, VaultManager
from companion_ui.workspace.vault_settings_panel import vault_settings_panel_markup


def _manager(tmp_path: Path, *, role: MachineRole = "primary") -> tuple[VaultManager, Path]:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    vault = tmp_path / f"vault-{role}"
    manager.initialize_vault(vault, machine_role=role, remember=False)
    return manager, vault


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def test_companion_writes_markdown_settings_scope(tmp_path: Path, monkeypatch) -> None:
    manager, vault = _manager(tmp_path)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    client = TestClient(app)

    shared = client.post(
        "/api/companion/vault/settings",
        json={"key": "handoffFolder", "value": "Client Handoff"},
    )
    assert shared.status_code == 200, shared.text
    shared_payload = shared.json()
    assert shared_payload["updated"]["scope"] == "vault-shared"
    assert shared_payload["updated"]["source_file"] == str(vault / "settings" / "paths.md")
    assert _frontmatter(vault / "settings" / "paths.md")["handoffFolder"] == "Client Handoff"
    assert "handoffFolder" not in _frontmatter(vault / "settings" / "local.md")

    local = client.post(
        "/api/companion/vault/settings",
        json={"key": "enableAutoIndexing", "value": False},
    )
    assert local.status_code == 200, local.text
    local_payload = local.json()
    assert local_payload["updated"]["scope"] == "vault-local"
    assert local_payload["updated"]["source_file"] == str(vault / "settings" / "local.md")
    assert _frontmatter(vault / "settings" / "local.md")["enableAutoIndexing"] is False
    assert "enableAutoIndexing" not in _frontmatter(vault / "settings" / "paths.md")


def test_settings_editor_respects_role_permissions(tmp_path: Path, monkeypatch) -> None:
    satellite, satellite_vault = _manager(tmp_path, role="satellite")
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: satellite)
    client = TestClient(app)

    blocked_shared = client.post(
        "/api/companion/vault/settings",
        json={"key": "handoffFolder", "value": "Satellite Handoff"},
    )
    assert blocked_shared.status_code == 403
    assert "shared settings edits disabled" in blocked_shared.text
    assert _frontmatter(satellite_vault / "settings" / "paths.md")["handoffFolder"] == "Design Handoff"

    allowed_local = client.post(
        "/api/companion/vault/settings",
        json={"key": "enableAutoIndexing", "value": False},
    )
    assert allowed_local.status_code == 200, allowed_local.text
    assert _frontmatter(satellite_vault / "settings" / "local.md")["enableAutoIndexing"] is False

    readonly, readonly_vault = _manager(tmp_path, role="readOnlySatellite")
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: readonly)
    blocked_local = client.post(
        "/api/companion/vault/settings",
        json={"key": "enableAutoIndexing", "value": True},
    )
    assert blocked_local.status_code == 403
    assert "writes disabled" in blocked_local.text
    assert _frontmatter(readonly_vault / "settings" / "local.md")["enableAutoIndexing"] is True

    projection = client.get("/api/companion/vault/settings")
    assert projection.status_code == 200, projection.text
    html = vault_settings_panel_markup(projection.json())
    assert 'data-setting-key="handoffFolder"' in html
    assert 'data-setting-key="enableAutoIndexing"' in html
    assert 'data-editable="false"' in html
    assert "writes disabled by machine role or local permission" in html
