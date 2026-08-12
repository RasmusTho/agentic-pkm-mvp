"""#2988 — a watcher scope that matches zero files must fail loud, not silently idle.

Two legs:
  * a scope glob whose static prefix directory exists but matches zero markdown
    files across a full tick -> heartbeat/status carries a visible "zero_match"
    degraded signal, and a warning is logged (at most once per interval).
  * a scope glob whose static prefix directory does not exist under the bound
    vault -> a fail-loud warning names the missing directory, and the tick does
    not silently report "healthy" with zero signal (no crash either — the
    #2005 idle-without-vault contract is untouched: this is a *bound* vault
    with a misconfigured scope, not an absent vault).
"""

from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

import pytest

import app.watcher.registry as registry
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _write_config(path: Path, *, scope_glob_expr: str = "${WATCHER_SCOPE_GLOB}") -> None:
    path.write_text(
        dedent(
            f"""\
            version: 1
            watchers:
              - name: ingest
                scope_glob: "{scope_glob_expr}"
                debounce_ms: 0
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def _base_env(monkeypatch: pytest.MonkeyPatch, *, vault_root: Path, tmp_path: Path, scope_glob: str) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", scope_glob)
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
    stop_file = tmp_path / "stop"
    monkeypatch.setenv("WATCHER_STOP_FILE", str(stop_file))
    if stop_file.exists():
        stop_file.unlink()
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_zero_match_sets_degraded_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)

    # The scope prefix directory exists, but nothing inside it matches *.md.
    scope_dir = vault_root / "📥 Inbox"
    scope_dir.mkdir(parents=True, exist_ok=True)
    (scope_dir / "not-markdown.txt").write_text("hello", encoding="utf-8")

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(monkeypatch, vault_root=vault_root, tmp_path=tmp_path, scope_glob="📥 Inbox/*.md")

    caplog.set_level(logging.WARNING, logger="app.watcher.registry")

    summaries = registry.run_registry_once(config_path)
    summary = summaries["ingest"]
    assert summary.get("scanned_files") == 1
    assert summary.get("scope_matched_files") == 0
    assert summary.get("scope_status") == "zero_match"

    import json

    heartbeat_path = Path(tmp_path / "heartbeat.json")
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["status"] == "degraded"
    assert payload["watchers"]["ingest"]["scope_status"] == "zero_match"

    messages = [rec.getMessage() for rec in caplog.records]
    assert any("zero" in msg.lower() and "ingest" in msg for msg in messages)

    # Warning is emitted at most once per interval: a second consecutive tick
    # within the same window must not duplicate the warning.
    caplog.clear()
    registry.run_registry_once(config_path)
    messages_second = [rec.getMessage() for rec in caplog.records]
    assert not any("zero" in msg.lower() and "ingest" in msg for msg in messages_second)


def test_settings_sources_do_not_mask_scope_zero_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    scope_dir = vault_root / "📥 Inbox"
    scope_dir.mkdir(parents=True, exist_ok=True)

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)
    _base_env(monkeypatch, vault_root=vault_root, tmp_path=tmp_path, scope_glob="📥 Inbox/*.md")

    summary = registry.run_registry_once(config_path)["ingest"]

    # Canonical settings remain a reloadable scan target outside this narrow
    # content scope, but they cannot suppress the zero-match health signal.
    assert summary.get("scanned_files") == 1
    assert summary.get("scope_matched_files") == 0
    assert summary.get("settings_source_reloads_in_tick") == 1
    assert summary.get("scope_status") == "zero_match"


def test_missing_scope_prefix_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    # Deliberately do NOT create "📥 Inbox" under the vault.
    missing_dir = vault_root / "📥 Inbox"
    assert not missing_dir.exists()

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(monkeypatch, vault_root=vault_root, tmp_path=tmp_path, scope_glob="📥 Inbox/*.md")

    caplog.set_level(logging.WARNING, logger="app.watcher.registry")

    # Must not raise / crash the tick loop.
    summaries = registry.run_registry_once(config_path)
    summary = summaries["ingest"]
    assert summary.get("scope_status") == "missing_prefix"

    messages = [rec.getMessage() for rec in caplog.records]
    assert any(str(missing_dir) in msg for msg in messages)

    import json

    heartbeat_path = Path(tmp_path / "heartbeat.json")
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["status"] == "degraded"
    assert payload["watchers"]["ingest"]["scope_status"] == "missing_prefix"
