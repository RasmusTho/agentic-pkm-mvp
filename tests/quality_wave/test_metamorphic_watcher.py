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
    emit_event: str = "ingest.vault.changed",
    backoff_seconds: int = 10,
) -> tuple[registry.RegistryConfig, registry.WatcherSpec]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    spec = registry.WatcherSpec(
        name="metamorphic",
        scope_glob=scope_glob,
        debounce_ms=debounce_ms,
        rate_limit_per_min=rate_limit,
        emit_event=emit_event,
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


def _install_fake_emit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_emit_watch_event(**kwargs) -> str:
        calls.append(kwargs)
        return uuid4().hex

    monkeypatch.setattr(registry, "_emit_watch_event", fake_emit_watch_event)
    return calls


def _write_note(path: Path, content: str, *, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _summary_key_fields(summary: dict[str, object]) -> dict[str, object]:
    return {
        "changed_in_tick": summary["changed_in_tick"],
        "scanned_files": summary["scanned_files"],
        "emitted_in_tick": summary["emitted_in_tick"],
        "hashed_files": summary["hashed_files"],
        "bytes_read": summary["bytes_read"],
        "rate_limited_in_tick": summary["rate_limited_in_tick"],
    }


@pytest.mark.parametrize("note_count", [1, 3])
def test_narrower_scope_fewer_or_equal_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    note_count: int,
) -> None:
    _install_fake_emit(monkeypatch)
    for idx in range(note_count):
        _write_note(tmp_path / "vault" / "Inbox" / f"inbox-{idx}.md", f"inbox {idx}", mtime=1_700_000_000 + idx)
    for idx in range(note_count + 1):
        _write_note(tmp_path / "vault" / "Archive" / f"archive-{idx}.md", f"archive {idx}", mtime=1_700_000_100 + idx)

    narrow_cfg, narrow_spec = _make_cfg(tmp_path / "narrow", scope_glob="Inbox/**")
    wide_cfg, wide_spec = _make_cfg(tmp_path / "wide", scope_glob="**/*.md")

    for source in (tmp_path / "vault").rglob("*.md"):
        rel = source.relative_to(tmp_path / "vault")
        _write_note(narrow_cfg.vault_path / rel, source.read_text(encoding="utf-8"), mtime=source.stat().st_mtime)
        _write_note(wide_cfg.vault_path / rel, source.read_text(encoding="utf-8"), mtime=source.stat().st_mtime)

    narrow_summary = registry._run_spec_tick(narrow_cfg, narrow_spec, WatcherState(), now=1_700_000_500.0)
    wide_summary = registry._run_spec_tick(wide_cfg, wide_spec, WatcherState(), now=1_700_000_500.0)

    assert narrow_summary["changed_in_tick"] <= wide_summary["changed_in_tick"]
    assert narrow_summary["scanned_files"] <= wide_summary["scanned_files"]


@pytest.mark.parametrize("note_count", [1, 4])
def test_more_ticks_unchanged_vault_same_total(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    note_count: int,
) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path)
    for idx in range(note_count):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_000 + idx)

    state = WatcherState()
    first = registry._run_spec_tick(cfg, spec, state, now=1_700_000_100.0)
    second = registry._run_spec_tick(cfg, spec, state, now=1_700_000_101.0)
    third = registry._run_spec_tick(cfg, spec, state, now=1_700_000_102.0)

    assert first["changed_in_tick"] == note_count
    assert second["changed_in_tick"] == 0
    assert third["changed_in_tick"] == 0
    assert state.changed_detected == note_count


@pytest.mark.parametrize("note_count", [1, 3])
def test_rate_limit_zero_no_emissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    note_count: int,
) -> None:
    calls = _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, rate_limit=0)
    for idx in range(note_count):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_000 + idx)

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_200.0)

    assert summary["changed_in_tick"] == note_count
    assert summary["emitted_in_tick"] == 0
    assert summary["rate_limited_in_tick"] == note_count
    assert calls == []


@pytest.mark.parametrize("scope_glob", ["Inbox/**", "**/*.md"])
def test_idempotent_same_params_same_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_glob: str,
) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, scope_glob=scope_glob)
    _write_note(cfg.vault_path / "Inbox" / "same.md", "stable", mtime=1_700_000_000)
    _write_note(cfg.vault_path / "Archive" / "other.md", "archive", mtime=1_700_000_100)

    summary_one = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_300.0)
    summary_two = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_300.0)

    assert _summary_key_fields(summary_one) == _summary_key_fields(summary_two)


@pytest.mark.parametrize("initial_count, added_count", [(2, 3), (1, 4)])
def test_more_notes_more_or_equal_scanned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_count: int,
    added_count: int,
) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path)
    for idx in range(initial_count):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_000 + idx)

    state = WatcherState()
    first = registry._run_spec_tick(cfg, spec, state, now=1_700_000_400.0)

    for idx in range(initial_count, initial_count + added_count):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_100 + idx)

    second = registry._run_spec_tick(cfg, spec, state, now=1_700_000_401.0)

    assert first["scanned_files"] == initial_count
    assert second["scanned_files"] >= first["scanned_files"]
    assert second["changed_in_tick"] == added_count


@pytest.mark.parametrize("max_scanned", [3, 5])
def test_max_scanned_files_caps_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_scanned: int,
) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, max_scanned=max_scanned)
    for idx in range(10):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_000 + idx)

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_500.0)

    assert summary["scanned_files"] == 10
    assert summary["bad_tick"] is True
    assert summary["bad_tick_reason"] == "too_many_files"


def test_empty_vault_zero_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path)

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_600.0)

    assert summary["changed_in_tick"] == 0
    assert summary["scanned_files"] == 0
    assert summary["emitted_in_tick"] == 0


@pytest.mark.parametrize("note_count", [1, 3])
def test_debounce_zero_processes_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    note_count: int,
) -> None:
    calls = _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, debounce_ms=0)
    for idx in range(note_count):
        _write_note(cfg.vault_path / "Inbox" / f"note-{idx}.md", f"payload {idx}", mtime=1_700_000_000 + idx)

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_700.0)

    assert summary["changed_in_tick"] == note_count
    assert summary["emitted_in_tick"] == note_count
    assert len(calls) == note_count


@pytest.mark.parametrize("scope_glob", ["**/*.md", "*.md,**/*.md"])
def test_scope_excludes_dotfolders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_glob: str,
) -> None:
    calls = _install_fake_emit(monkeypatch)
    cfg, spec = _make_cfg(tmp_path, scope_glob=scope_glob)
    _write_note(cfg.vault_path / ".obsidian" / "settings.md", "hidden", mtime=1_700_000_000)
    _write_note(cfg.vault_path / "Inbox" / "visible.md", "visible", mtime=1_700_000_001)

    summary = registry._run_spec_tick(cfg, spec, WatcherState(), now=1_700_000_800.0)

    assert summary["scanned_files"] == 1
    assert summary["changed_in_tick"] == 1
    assert len(calls) == 1
    assert calls[0]["rel_path"] == Path("Inbox/visible.md")
