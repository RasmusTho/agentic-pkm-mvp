from __future__ import annotations

from pathlib import Path

import app.vault.app_local as app_local
from app.vault.app_local import (
    AppLocalSettingsStore,
    KnownVaultRef,
    default_app_local_settings_path,
)


def test_known_vault_registry_round_trips(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/main", path="/vaults/main", vault_id="vault-1"))
    loaded = store.load()

    assert loaded.app_install_id.startswith("app-")
    assert loaded.last_active_vault_ref == "path:/vaults/main"
    assert loaded.known_vaults["path:/vaults/main"].vault_id == "vault-1"


def test_missing_known_vault_path_is_preserved_for_repair(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/missing", path="/missing", vault_id="vault-1"))

    assert store.load().known_vaults["path:/missing"].path == "/missing"


def test_same_vault_id_at_multiple_paths_keeps_separate_refs(tmp_path) -> None:
    store = AppLocalSettingsStore(tmp_path / "app-local.md")

    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/main", path="/vaults/main", vault_id="same"))
    store.upsert_known_vault(KnownVaultRef(ref="path:/vaults/clone", path="/vaults/clone", vault_id="same"))
    loaded = store.load()

    assert sorted(loaded.known_vaults) == ["path:/vaults/clone", "path:/vaults/main"]
    assert loaded.known_vaults["path:/vaults/main"].path != loaded.known_vaults["path:/vaults/clone"].path


def _make_hostless(monkeypatch, runtime_dir: Path) -> None:
    """Simulate a container UID with no usable HOME and a writable runtime dir."""
    monkeypatch.delenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "/")
    monkeypatch.setattr(app_local.Path, "home", staticmethod(lambda: Path("/")))
    monkeypatch.setattr(app_local, "_CONTAINER_RUNTIME_DIR", runtime_dir, raising=False)


def test_hostless_home_does_not_resolve_under_library(tmp_path, monkeypatch) -> None:
    # Regression: hostless container UID (HOME=/ , no passwd entry) must not
    # resolve under /Library/... and must land in a writable runtime dir.
    runtime_dir = tmp_path / "app-tmp"
    runtime_dir.mkdir()
    _make_hostless(monkeypatch, runtime_dir)

    path = default_app_local_settings_path()

    assert "Library/Application Support" not in str(path)
    assert path == runtime_dir / "agentic-pkm" / "app-local.md"
    # The store can actually create and write it without crashing.
    AppLocalSettingsStore(path).upsert_known_vault(
        KnownVaultRef(ref="path:/vaults/main", path="/vaults/main")
    )
    assert path.exists()


def test_override_wins_over_hostless_home(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "app-tmp"
    runtime_dir.mkdir()
    _make_hostless(monkeypatch, runtime_dir)
    override = tmp_path / "override" / "app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(override))

    assert default_app_local_settings_path() == override


def test_xdg_data_home_preferred_when_set(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "app-tmp"
    runtime_dir.mkdir()
    _make_hostless(monkeypatch, runtime_dir)
    xdg = tmp_path / "xdg-data"
    xdg.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    path = default_app_local_settings_path()

    assert path == xdg / "Agentic PKM" / "app-local.md"


def test_unset_home_with_no_passwd_entry_falls_back(tmp_path, monkeypatch) -> None:
    # HOME unset and Path.home() raising (no passwd entry) must not crash.
    runtime_dir = tmp_path / "app-tmp"
    runtime_dir.mkdir()
    monkeypatch.delenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)

    def _raise() -> Path:
        raise RuntimeError("no home directory")

    monkeypatch.setattr(app_local.Path, "home", staticmethod(_raise))
    monkeypatch.setattr(app_local, "_CONTAINER_RUNTIME_DIR", runtime_dir, raising=False)

    path = default_app_local_settings_path()

    assert path == runtime_dir / "agentic-pkm" / "app-local.md"


def test_usable_home_preserves_library_path(tmp_path, monkeypatch) -> None:
    # Prod-as-root / macOS host: a writable HOME keeps the Library path.
    monkeypatch.delenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(app_local.Path, "home", staticmethod(lambda: home))

    path = default_app_local_settings_path()

    assert path == home / "Library" / "Application Support" / "Agentic PKM" / "app-local.md"
