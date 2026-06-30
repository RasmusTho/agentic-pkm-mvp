from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
import yaml

import app.watcher.registry as registry
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.settings_service import SettingsService
from app.watcher.settings_delta import SETTINGS_LOCAL_REL, handle_settings_local_delta
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _write_watchers_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: ""
                debounce_ms: 0
                rate_limit_per_min: 30
                emit_event: "panel.scan.requested"
              - name: ingest
                scope_glob: ""
                debounce_ms: 0
                rate_limit_per_min: 30
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def _touch(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


def _read_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def _write_local_settings(vault_root: Path, updates: dict[str, object]) -> Path:
    store = MarkdownSettingsStore()
    local_md = vault_root / "settings" / "local.md"
    document = store.read(local_md)
    frontmatter = dict(document.frontmatter)
    frontmatter.update(updates)
    store.write_frontmatter(local_md, frontmatter, body=document.body)
    return local_md


def test_multiple_watcher_specs_emit_one_settings_receipt_per_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    VaultManager().initialize_vault(vault_root, machine_role="primary", remember=False)

    config_path = tmp_path / "watchers.yaml"
    _write_watchers_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    registry.run_registry_once(config_path)

    local_md = _write_local_settings(vault_root, {"enableAutoIndexing": False})
    _touch(local_md, 1_700_000_050.0)

    summaries = registry.run_registry_once(config_path)
    total_receipts = sum(int(summary.get("settings_receipts_in_tick", 0)) for summary in summaries.values())

    assert total_receipts == 1
    assert summaries["panel"]["changed_in_tick"] >= 1
    assert summaries["ingest"]["changed_in_tick"] >= 1
    assert summaries["panel"]["emitted_in_tick"] >= 1
    assert summaries["ingest"]["emitted_in_tick"] >= 1


def test_runtime_gating_key_removal_routes_settings_receipt(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)

    local_md = vault_root / "settings" / "local.md"
    previous_values = {
        key: value
        for key, value in _read_frontmatter(local_md).items()
        if key in {"enableVaultWatcher", "enableAutoIndexing"}
    }
    assert "enableAutoIndexing" in previous_values

    store = MarkdownSettingsStore()
    document = store.read(local_md)
    frontmatter = dict(document.frontmatter)
    frontmatter.pop("enableAutoIndexing", None)
    store.write_frontmatter(local_md, frontmatter, body=document.body)
    _touch(local_md, 1_700_000_090.0)

    captured_calls: list[tuple[str, object, str, str, bool]] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService, context, key, value, *, surface="api", actor="human", persist=True
    ):
        captured_calls.append((key, value, surface, actor, persist))
        return original_update(self, context, key, value, surface=surface, actor=actor, persist=persist)

    with patch.object(SettingsService, "update_setting", _spy_update):
        result = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_LOCAL_REL,
            previous_values=previous_values,
        )

    assert result.errors == ()
    assert result.values is not None
    assert "enableAutoIndexing" not in result.values
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt.key == "enableAutoIndexing"
    assert receipt.surface == "file"
    assert receipt.actor == "human"
    assert receipt.is_runtime_gating is True
    assert captured_calls == [("enableAutoIndexing", receipt.value, "file", "human", False)]
    assert "enableAutoIndexing" not in _read_frontmatter(local_md)
