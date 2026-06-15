from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_readonly_satellite_vault(vault_root: Path) -> Path:
    """A readOnlySatellite clone that still has allowLocalSettingsEdits=true."""
    settings_dir = vault_root / "settings"
    _write(
        settings_dir / "vault.md",
        "---\nschema: design-handoff.vault.v1\nscope: vault-shared\nvaultId: v\nvaultName: X\n---\n",
    )
    _write(
        settings_dir / "paths.md",
        "---\nscope: vault-shared\nhandoffFolder: Design Handoff\n"
        "assetsFolder: Design Handoff/Assets\ntemplatesFolder: Design Handoff/Templates\n"
        "archiveFolder: Design Handoff/Archive\n---\n",
    )
    for name in ("workflow.md", "design-handoff.md", "companion-ui.md"):
        _write(settings_dir / name, "---\nscope: vault-shared\n---\n")
    _write(
        settings_dir / "local.md",
        "---\nschema: design-handoff.local.v1\nscope: vault-local\nlocalInstanceId: l1\n"
        "machineRole: readOnlySatellite\nallowLocalSettingsEdits: true\n"
        "allowWritesToVault: false\nallowSharedSettingsEdits: false\n---\n",
    )
    return settings_dir


@pytest.mark.parametrize(
    "key,value",
    [
        ("machineRole", "primary"),
        ("allowWritesToVault", True),
        ("allowSharedSettingsEdits", True),
    ],
)
def test_readonly_local_edit_blocks_role_escalation(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: object,
) -> None:
    """A readOnlySatellite (even with allowLocalSettingsEdits=true) must not be able
    to grant itself project-write authority by editing authority-bearing vault-local keys."""
    vault_root = tmp_path / "vault"
    _init_readonly_satellite_vault(vault_root)

    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    context = manager.select_vault(vault_root, remember=False)
    assert context.machine_role == "readOnlySatellite"
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)

    resp = client.post("/api/companion/vault/settings", json={"key": key, "value": value})

    assert resp.status_code == 403, resp.text
    # The on-disk local.md must be unchanged: no escalation was persisted.
    local_md = (vault_root / "settings" / "local.md").read_text(encoding="utf-8")
    assert "machineRole: readOnlySatellite" in local_md
    assert "allowWritesToVault: false" in local_md


def test_readonly_local_edit_allows_benign_local_key(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: a non-authority local key remains editable when
    allowLocalSettingsEdits is true (the read-only ceiling is not over-broad)."""
    vault_root = tmp_path / "vault"
    _init_readonly_satellite_vault(vault_root)
    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=tmp_path / "app-local.md"))
    manager.select_vault(vault_root, remember=False)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)

    resp = client.post(
        "/api/companion/vault/settings",
        json={"key": "localExportPath", "value": "/tmp/export"},
    )

    assert resp.status_code == 200, resp.text


def test_corrupt_last_active_falls_back(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt app-local last-active registry must degrade to the no-vault picker
    state instead of raising a 500 on vault data/edit routes."""
    corrupt_app_local = tmp_path / "app-local.md"
    # Git conflict markers make the markdown settings file unreadable.
    corrupt_app_local.write_text(
        "---\n<<<<<<< HEAD\nappInstallId: a\n=======\nappInstallId: b\n>>>>>>> branch\n---\n",
        encoding="utf-8",
    )
    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=corrupt_app_local))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    monkeypatch.delenv("VAULT_ROOT", raising=False)

    # Data route (settings) must not 500.
    settings_resp = client.get("/api/companion/vault/settings")
    assert settings_resp.status_code == 200, settings_resp.text

    # Context route must not 500 either.
    context_resp = client.get("/api/companion/vault/context")
    assert context_resp.status_code == 200, context_resp.text
