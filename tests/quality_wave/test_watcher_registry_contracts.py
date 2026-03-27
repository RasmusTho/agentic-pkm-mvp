from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.watcher import registry
from app.watcher.state import WatcherState

pytestmark = pytest.mark.not_pg


def _make_cfg(
    tmp_path: Path,
    *,
    scope_glob: str = "**/*.md",
    rate_limit: int = 60,
    max_scanned: int = 100,
    debounce_ms: int = 0,
    backoff_seconds: int = 10,
) -> tuple[registry.RegistryConfig, registry.WatcherSpec]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    spec = registry.WatcherSpec(
        name="contract",
        scope_glob=scope_glob,
        debounce_ms=debounce_ms,
        rate_limit_per_min=rate_limit,
        emit_event="ingest.vault.changed",
        backoff_seconds=backoff_seconds,
    )
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob=scope_glob,
        debounce_ms=debounce_ms,
        rate_limit_per_min=rate_limit,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "tick.jsonl",
        max_scanned_files_per_tick=max_scanned,
        max_bytes_read_per_tick=1_000_000,
        max_elapsed_ms_per_tick=10_000,
        max_bad_ticks=5,
        bad_tick_backoff_seconds=1.0,
        specs=[spec],
    )
    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    return cfg, spec


def _write_note(path: Path, content: str, *, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _install_fake_emit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_emit_watch_event(**kwargs) -> str:
        calls.append(kwargs)
        return uuid4().hex

    monkeypatch.setattr(registry, "_emit_watch_event", fake_emit_watch_event)
    return calls


def _run_tick(
    monkeypatch: pytest.MonkeyPatch,
    cfg: registry.RegistryConfig,
    spec: registry.WatcherSpec,
    state: WatcherState,
    *,
    now: float,
) -> dict[str, object]:
    monkeypatch.setattr(registry.time, "time", lambda: now)
    return registry._run_spec_tick(cfg, spec, state, now=now)


def test_tick_summary_tracks_state_accumulation_and_rate_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, rate_limit=1)
    note = cfg.vault_path / "Inbox" / "note.md"
    _write_note(note, "v1", mtime=1_700_001_000)

    state = WatcherState()
    first = _run_tick(monkeypatch, cfg, spec, state, now=1_700_001_100.0)

    _write_note(note, "v2", mtime=1_700_001_101)
    second = _run_tick(monkeypatch, cfg, spec, state, now=1_700_001_101.0)

    assert first["changed_in_tick"] == 1
    assert first["emitted_in_tick"] == 1
    assert second["changed_in_tick"] == 1
    assert second["emitted_in_tick"] == 0
    assert second["rate_limited_in_tick"] == 1
    assert second["changed_detected"] == state.changed_detected == 2
    assert second["intents_emitted"] == state.intents_emitted == 1
    assert state.changed_detected >= state.intents_emitted
    assert len(calls) == 1


def test_backoff_tick_short_circuits_scanning_until_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, spec = _make_cfg(tmp_path, backoff_seconds=30)
    _write_note(cfg.vault_path / "Inbox" / "note.md", "payload", mtime=1_700_002_000)

    def boom(**kwargs) -> str:
        raise RuntimeError("emit failed")

    monkeypatch.setattr(registry, "_emit_watch_event", boom)

    state = WatcherState()
    first = _run_tick(monkeypatch, cfg, spec, state, now=1_700_002_100.0)
    second = _run_tick(monkeypatch, cfg, spec, state, now=1_700_002_110.0)

    assert first["changed_in_tick"] == 1
    assert first["backoff_active"] is True
    assert state.backoff_until == 1_700_002_130.0
    assert second["backoff_active"] is True
    assert second["scanned_files"] == 0
    assert second["changed_in_tick"] == 0
    assert second["emitted_in_tick"] == 0
    assert state.intents_emitted == 0


def test_bad_tick_resets_after_following_healthy_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, max_scanned=1)
    one = cfg.vault_path / "Inbox" / "one.md"
    two = cfg.vault_path / "Inbox" / "two.md"
    _write_note(one, "one", mtime=1_700_003_000)
    _write_note(two, "two", mtime=1_700_003_001)

    state = WatcherState()
    bad = _run_tick(monkeypatch, cfg, spec, state, now=1_700_003_100.0)
    assert bad["bad_tick"] is True
    assert state.bad_ticks == 1

    two.unlink()
    cfg.max_scanned_files_per_tick = 2
    healthy = _run_tick(monkeypatch, cfg, spec, state, now=1_700_003_200.0)

    assert healthy["bad_tick"] is False
    assert healthy["bad_tick_reason"] is None
    assert state.bad_ticks == 0
    assert healthy["chosen_sleep_seconds"] == cfg.tick_sleep_seconds
    assert state.dynamic_sleep_seconds is None


def test_derive_scan_root_rejects_parent_escape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "outside").mkdir()

    with pytest.raises(ValueError):
        registry._derive_scan_root(vault, "../outside/**")


def test_derive_scan_root_uses_specific_scope_prefix(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)

    scan_root = registry._derive_scan_root(vault, "Inbox/**")

    assert scan_root == inbox


def test_derive_scan_root_stays_at_vault_for_vaultwide_scope(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    scan_root = registry._derive_scan_root(vault, "*.md,**/*.md")

    assert scan_root == vault


def test_derive_scan_root_fails_for_missing_prefixed_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(FileNotFoundError):
        registry._derive_scan_root(vault, "Missing/**")
