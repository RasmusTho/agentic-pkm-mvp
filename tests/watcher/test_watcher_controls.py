from __future__ import annotations

import json
import os
from pathlib import Path

from app.watcher.config import WatcherConfig
from app.watcher.state import WatcherState
from app.watcher.watcher import run_tick


def _config(tmp_path: Path, *, rate_limit: int = 30, debounce_ms: int = 1500) -> WatcherConfig:
    return WatcherConfig(
        enable=True,
        vault_path=tmp_path / "vault",
        scope_glob="@Inbox/**",
        debounce_ms=debounce_ms,
        rate_limit_per_min=rate_limit,
        backoff_seconds=10,
        state_path=tmp_path / "state.json",
        stop_file=tmp_path / "WATCHER_STOP",
        outbox_path=tmp_path / "outbox.jsonl",
        summary_interval=10,
        tick_sleep_seconds=0.0,
    )


def _read_outbox(outbox: Path) -> list[dict]:
    if not outbox.exists():
        return []
    lines = outbox.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_scope_glob_limits_to_inbox(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    inbox = cfg.vault_path / "@Inbox"
    inbox.mkdir()
    other_dir = cfg.vault_path / "Other"
    other_dir.mkdir()

    inbox_note = inbox / "note.md"
    inbox_note.write_text("hello", encoding="utf-8")
    other_note = other_dir / "skip.md"
    other_note.write_text("ignored", encoding="utf-8")

    state = WatcherState()
    summary = run_tick(cfg, state, now=0.0)

    assert summary["emitted_in_tick"] == 1
    entries = _read_outbox(cfg.outbox_path)
    assert len(entries) == 1
    payload = entries[0].get("payload") or {}
    assert payload.get("relative_path") == str(Path("@Inbox") / inbox_note.name)
    assert other_note.name not in cfg.outbox_path.read_text(encoding="utf-8")


def test_debounce_blocks_rapid_retriggers(tmp_path: Path) -> None:
    cfg = _config(tmp_path, debounce_ms=1500)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    note = (cfg.vault_path / "@Inbox").joinpath("note.md")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("v1", encoding="utf-8")

    state = WatcherState()
    first = run_tick(cfg, state, now=0.0)
    assert first["emitted_in_tick"] == 1

    note.write_text("v2", encoding="utf-8")
    os.utime(note, None)
    second = run_tick(cfg, state, now=0.5)
    assert second["emitted_in_tick"] == 0


def test_rate_limit_blocks_after_threshold(tmp_path: Path) -> None:
    cfg = _config(tmp_path, rate_limit=1)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    note = (cfg.vault_path / "@Inbox").joinpath("rate.md")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("first", encoding="utf-8")

    state = WatcherState()
    first = run_tick(cfg, state, now=0.0)
    assert first["emitted_in_tick"] == 1

    note.write_text("second", encoding="utf-8")
    os.utime(note, None)
    second = run_tick(cfg, state, now=2.0)
    assert second["emitted_in_tick"] == 0
    assert second["rate_limited_in_tick"] == 1

    entries = _read_outbox(cfg.outbox_path)
    assert len(entries) == 1


def test_kill_switch_pauses_without_emitting(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    note = (cfg.vault_path / "@Inbox").joinpath("stop.md")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("halt", encoding="utf-8")

    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.stop_file.write_text("stop", encoding="utf-8")

    state = WatcherState()
    summary = run_tick(cfg, state, now=0.0)

    assert summary["kill_switch"] is True
    assert summary["emitted_in_tick"] == 0
    assert not cfg.outbox_path.exists() or cfg.outbox_path.read_text(encoding="utf-8").strip() == ""


def test_restart_sanitizes_monotonic_state(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    note = (cfg.vault_path / "@Inbox").joinpath("restart.md")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("v1", encoding="utf-8")

    rel = str(Path("@Inbox") / note.name)
    state_payload = {
        "files": {rel: {"last_seen": 123.45, "last_emitted": 234.56, "hash": "old", "mtime": 1.0}},
        "backoff_until": 456.78,
        "rate_window": [111.0, 222.0],
        "changed_detected": 5,
        "intents_emitted": 2,
    }
    cfg.state_path.write_text(json.dumps(state_payload), encoding="utf-8")

    state = WatcherState.load(cfg.state_path)
    now1 = note.stat().st_mtime + 10
    summary1 = run_tick(cfg, state, now=now1)
    assert summary1["emitted_in_tick"] == 1
    assert summary1["backoff_active"] is False

    entries1 = _read_outbox(cfg.outbox_path)
    assert len(entries1) == 1

    new_state = WatcherState.load(cfg.state_path)
    note.write_text("v2", encoding="utf-8")
    now2 = now1 + 20
    os.utime(note, (now2, now2))
    summary2 = run_tick(cfg, new_state, now=now2)
    assert summary2["emitted_in_tick"] == 1
    entries2 = _read_outbox(cfg.outbox_path)
    assert len(entries2) == 2
