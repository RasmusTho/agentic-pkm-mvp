from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.watcher.registry import RegistryConfig, WatcherSpec


def _write_layout_note(vault_root: Path, *, system_folder: str, inbox_folder: str) -> None:
    system = vault_root / system_folder
    system.mkdir(parents=True, exist_ok=True)
    note = system / "vault.layout.md"
    note.write_text(
        "---\n"
        "version: '1'\n"
        f"system_folder: '{system_folder}'\n"
        f"inbox_folder: '{inbox_folder}'\n"
        "desk_folder: 'Workbench'\n"
        "root_folders: []\n"
        "---\n\n"
        "# layout\n",
        encoding="utf-8",
    )


def _make_specs() -> list[WatcherSpec]:
    return [
        WatcherSpec(
            name="ingest",
            scope_glob="",
            debounce_ms=0,
            rate_limit_per_min=0,
            emit_event="ingest.vault.changed",
        )
    ]


def test_registry_scope_env_takes_precedence(tmp_path: Path, monkeypatch, caplog) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    _write_layout_note(vault_root, system_folder="System", inbox_folder="Input")

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "custom/scope/**")
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    caplog.set_level(logging.INFO, logger="app.watcher.registry")

    cfg = RegistryConfig.from_env(_make_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.scope_glob == "custom/scope/**"

    joined = "\n".join(r.message for r in caplog.records)
    assert "watcher scope resolved" in joined
    assert "provenance=env:WATCHER_SCOPE_GLOB" in joined


def test_registry_scope_defaults_to_vault_layout_inbox(tmp_path: Path, monkeypatch, caplog) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    _write_layout_note(vault_root, system_folder="System", inbox_folder="Input")

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.delenv("WATCHER_SCOPE_GLOB", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    caplog.set_level(logging.INFO, logger="app.watcher.registry")

    cfg = RegistryConfig.from_env(_make_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.scope_glob == "*.md,**/*.md"

    joined = "\n".join(r.message for r in caplog.records)
    assert "watcher scope resolved" in joined
    assert "provenance=default:vaultwide" in joined


def test_registry_scope_blank_is_treated_as_unset(tmp_path: Path, monkeypatch, caplog) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    _write_layout_note(vault_root, system_folder="System", inbox_folder="Input")

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "   ")
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    caplog.set_level(logging.INFO, logger="app.watcher.registry")

    cfg = RegistryConfig.from_env(_make_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.scope_glob == "*.md,**/*.md"

    joined = "\n".join(r.message for r in caplog.records)
    assert "watcher scope resolved" in joined
    assert "provenance=default:vaultwide" in joined


@pytest.mark.parametrize(
    "env_value",
    ["", "   ", "\t\n"],
)
def test_registry_scope_blank_ignores_vault_inbox_override(
    tmp_path: Path, monkeypatch, caplog, env_value: str
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    _write_layout_note(vault_root, system_folder="System", inbox_folder="Input")

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", env_value)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "AltInput")

    caplog.set_level(logging.INFO, logger="app.watcher.registry")

    cfg = RegistryConfig.from_env(_make_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.scope_glob == "*.md,**/*.md"

    joined = "\n".join(r.message for r in caplog.records)
    assert "provenance=default:vaultwide" in joined
