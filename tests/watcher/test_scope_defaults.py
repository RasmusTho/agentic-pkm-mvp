from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.watcher.config import DEFAULT_SCOPE_GLOB, WatcherConfig
from app.watcher.registry import load_registry_config
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _write_registry_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: ""
                debounce_ms: 50
                rate_limit_per_min: 120
                emit_event: "panel.scan.requested"
              - name: ingest
                scope_glob: ""
                debounce_ms: 50
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def test_watcher_config_defaults_vaultwide(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    initialize_test_vault(tmp_path)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("WATCHER_SCOPE_GLOB", raising=False)

    cfg = WatcherConfig.from_env()
    assert cfg.scope_glob == DEFAULT_SCOPE_GLOB


def test_registry_config_defaults_vaultwide(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_test_vault(vault)

    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.delenv("WATCHER_SCOPE_GLOB", raising=False)

    cfg = load_registry_config(config_path)
    assert cfg.scope_glob == DEFAULT_SCOPE_GLOB


def test_watcher_scope_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initialize_test_vault(vault)

    override = "notes/**/*.md"
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", override)

    cfg = WatcherConfig.from_env()
    assert cfg.scope_glob == override
