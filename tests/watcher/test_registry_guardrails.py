from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.vault.manager import VaultManager
from app.watcher import registry
from app.watcher.state import WatcherState

pytestmark = pytest.mark.watcher_controls


def test_registry_scan_root_and_mtime_caching(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    inbox_dir = vault / "Inbox"
    inbox_dir.mkdir()
    other_dir = vault / "Other"
    other_dir.mkdir()
    note = inbox_dir / "note.md"
    note.write_text("agenda", encoding="utf-8")
    (other_dir / "skip.md").write_text("ignored", encoding="utf-8")

    spec = registry.WatcherSpec(
        name="panel",
        scope_glob="Inbox/**",
        debounce_ms=1500,
        rate_limit_per_min=60,
        emit_event="ingest.vault.changed",
        backoff_seconds=10,
    )
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="Inbox/**",
        debounce_ms=1500,
        rate_limit_per_min=60,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "tick.jsonl",
        max_scanned_files_per_tick=100,
        max_bytes_read_per_tick=1_000_000,
        max_elapsed_ms_per_tick=10_000,
        max_bad_ticks=5,
        bad_tick_backoff_seconds=1.0,
        specs=[spec],
    )
    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    calls: list[Path] = []
    original_hash = registry._hash_file

    def fake_hash(path: Path) -> tuple[str, int] | None:
        calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(registry, "_hash_file", fake_hash)

    def fake_emit_watch_event(**kwargs) -> str:
        return uuid4().hex

    monkeypatch.setattr(registry, "_emit_watch_event", fake_emit_watch_event)

    state = WatcherState()
    first = registry._run_spec_tick(cfg, spec, state, now=0.0)
    assert first["scanned_files"] == 1
    assert len(calls) == 1

    second = registry._run_spec_tick(cfg, spec, state, now=1.0)
    assert second["scanned_files"] == 1
    assert len(calls) == 1


def test_registry_layoutless_initialized_vault_ordinary_note_tick_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_LAYOUT_NOTE_REL", raising=False)

    def fail_layout_provisioning(_vault_root: Path):
        raise OSError("layout provisioning unavailable")

    monkeypatch.setattr(
        "app.vault.layout.load_or_create_layout", fail_layout_provisioning
    )
    VaultManager().initialize_vault(vault, machine_role="testNode", remember=False)
    assert (vault / "settings" / "vault.md").exists()
    assert not list(vault.rglob("vault.layout.md"))

    note = vault / "Notes" / "ordinary.md"
    note.parent.mkdir()
    note.write_text("ordinary note", encoding="utf-8")
    spec = registry.WatcherSpec(
        name="ingest",
        scope_glob="Notes/**",
        debounce_ms=0,
        rate_limit_per_min=60,
        emit_event="ingest.vault.changed",
        backoff_seconds=10,
    )
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="Notes/**",
        debounce_ms=0,
        rate_limit_per_min=60,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "tick.jsonl",
        max_scanned_files_per_tick=100,
        max_bytes_read_per_tick=1_000_000,
        max_elapsed_ms_per_tick=10_000,
        max_bad_ticks=5,
        bad_tick_backoff_seconds=1.0,
        specs=[spec],
    )

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=0.0)

    assert summary["emitted_in_tick"] == 1
    records = [
        line
        for line in cfg.outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert "Notes/ordinary.md" in records[0]
