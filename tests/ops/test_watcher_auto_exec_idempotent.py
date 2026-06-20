from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.stores import reset_store_backends
from app.watcher.vault_watcher import (
    _PANEL_POLICY_ID,
    _DEDUP_QUEUE,
    _build_dedup_key,
    _content_hash,
    run_watcher_tick,
)

def _write_watchers_file(vault: Path, content: str) -> Path:
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    watcher_file = settings_dir / "watchers.md"
    watcher_file.write_text(content, encoding="utf-8")
    return watcher_file


pytestmark = pytest.mark.not_pg


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _panel_note(title: str, auto_run: str = "watcher") -> str:
    return f"""---\nuuid: 11111111-1111-1111-1111-111111111111\ntitle: {title}\nai_panel_auto_run: {auto_run}\n---\n%% AI:Start %%\n## AI-instruktion\nDo work\n## AI-åtgärder\n- [x] Gör denna anteckning evergreen\n%% AI:End %%\n"""


def _read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _note_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_auto_exec_disabled_no_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "A.md"
    _write(note_path, _panel_note("A"))

    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "0")

    before = _note_digest(note_path)
    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=tmp_path / "snapshot.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after = _note_digest(note_path)
    assert before == after
    assert summary.get("panel_runs", 0) == 0
    assert summary.get("panel_skipped_auto_exec", 0) == 1

    events = _read_events(outbox)
    topics = {entry.get("event") for entry in events}
    assert "panel.intent.created" not in topics
    assert "promote.intent.created" not in topics


def test_auto_exec_policy_denied_never(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "Manual.md"
    _write(note_path, _panel_note("Manual", auto_run="never"))

    outbox = tmp_path / "outbox.jsonl"
    telemetry_log = tmp_path / "watcher_run.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    # Route watcher.run telemetry to dedicated path (#2253: never index-outbox).
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(telemetry_log))

    before = _note_digest(note_path)
    summary, messages = run_watcher_tick(
        vault_root=vault,
        snapshot_path=tmp_path / "snapshot.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after = _note_digest(note_path)
    assert before == after
    assert summary.get("panel_runs", 0) == 0
    assert summary.get("panel_skipped_policy", 0) == 1
    assert summary.get("panel_skipped_auto_exec", 0) == 0
    assert any("policy denies auto-run" in msg for msg in messages)
    # watcher.run goes to dedicated telemetry log, not index-outbox (#2253).
    telemetry_events = _read_events(telemetry_log)
    telemetry_topics = {entry.get("event") for entry in telemetry_events}
    assert "watcher.run" in telemetry_topics
    events = _read_events(outbox)
    topics = {entry.get("event") for entry in events}
    assert "panel.intent.created" not in topics


def test_auto_exec_disallowed_action_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "Archive.md"
    note = """---
uuid: 22222222-2222-2222-2222-222222222222
title: Archive
ai_panel_auto_run: watcher
---
%% AI:Start %%
## AI-instruktion
Dont run
## AI-åtgärder
- [x] Archive this note
%% AI:End %%
"""
    _write(note_path, note)

    outbox = tmp_path / "outbox.jsonl"
    telemetry_log = tmp_path / "watcher_run.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    # Route watcher.run telemetry to dedicated path (#2253: never index-outbox).
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(telemetry_log))

    _write_watchers_file(
        vault,
        """---
auto_run:
  allowed_actions:
    - promote.evergreen
paths:
  index_outbox: tmp/index-outbox.jsonl
  watcher_tick_log: tmp/watcher_tick.jsonl
  panel_event_log: tmp/index-outbox.jsonl
---
""",
    )

    before = _note_digest(note_path)
    summary, messages = run_watcher_tick(
        vault_root=vault,
        snapshot_path=tmp_path / "snapshot.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after = _note_digest(note_path)
    assert before == after
    assert summary.get("panel_skipped_allowed_actions", 0) == 1
    assert summary.get("panel_runs", 0) == 0
    assert any("not in allowed set" in msg for msg in messages)

    # watcher.run goes to dedicated telemetry log, not index-outbox (#2253).
    telemetry_events = _read_events(telemetry_log)
    telemetry_topics = {entry.get("event") for entry in telemetry_events}
    assert "watcher.run" in telemetry_topics
    events = _read_events(outbox)
    topics = {entry.get("event") for entry in events}
    assert "promote.intent.created" not in topics


def test_watcher_dedup_skips_second_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "A.md"
    _write(note_path, _panel_note("A"))

    outbox = tmp_path / "outbox.jsonl"
    snapshot = tmp_path / "snapshot.json"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    _write_watchers_file(
        vault,
        """---
auto_run:
  allowed_actions:
    - promote.evergreen
paths:
  index_outbox: tmp/index-outbox.jsonl
  watcher_tick_log: tmp/watcher_tick.jsonl
  panel_event_log: tmp/index-outbox.jsonl
---
""",
    )

    rel = note_path.relative_to(vault)
    dedup_key = _build_dedup_key(_PANEL_POLICY_ID, rel, _content_hash(note_path.read_text()))
    assert _DEDUP_QUEUE.try_acquire(dedup_key)
    try:
        summary, _ = run_watcher_tick(
            vault_root=vault,
            snapshot_path=snapshot,
            skip_panel=False,
            emit_only=True,
            dry_run=False,
            max_notes=10,
            force=False,
            outbox_path=outbox,
        )
    finally:
        _DEDUP_QUEUE.release(dedup_key)

    assert summary.get("panel_runs", 0) == 0
    assert summary.get("skipped_dedup", 0) == 1

def test_auto_exec_enabled_two_runs_are_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "A.md"
    _write(note_path, _panel_note("A"))

    outbox = tmp_path / "outbox.jsonl"
    snapshot = tmp_path / "snapshot.json"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    before = _note_digest(note_path)
    summary1, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot,
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after_first = _note_digest(note_path)
    assert before != after_first
    assert summary1.get("panel_runs", 0) == 1

    events_after_first = _read_events(outbox)
    first_count = len(events_after_first)

    summary2, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot,
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after_second = _note_digest(note_path)
    assert after_second == after_first
    assert summary2.get("changed", 0) == 0

    events_after_second = _read_events(outbox)
    new_events = events_after_second[first_count:]
    assert all(entry.get("event") == "watcher.run" for entry in new_events)


def test_auto_exec_blocked_by_write_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "A.md"
    _write(note_path, _panel_note("A"))

    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    monkeypatch.setattr(
        "app.write_guard.DEFAULT_WRITE_GUARD.snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "tests"},
    )

    before = _note_digest(note_path)
    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=tmp_path / "snapshot.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=outbox,
    )

    after = _note_digest(note_path)
    assert after == before
    assert summary.get("skipped_writes_blocked", 0) == 1
    assert summary.get("panel_runs", 0) == 0

    events = _read_events(outbox)
    topics = {entry.get("event") for entry in events}
    assert "panel.intent.created" not in topics
    assert "promote.intent.created" not in topics


def test_watcher_dedup_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    rel = Path("Notes") / "D.md"
    note_path = vault / rel
    body = _panel_note("D")
    _write(note_path, body)

    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    dedup_key = _build_dedup_key(_PANEL_POLICY_ID, rel, _content_hash(body))
    assert _DEDUP_QUEUE.try_acquire(dedup_key)
    try:
        before = _note_digest(note_path)
        summary, _ = run_watcher_tick(
            vault_root=vault,
            snapshot_path=tmp_path / "snapshot.json",
            skip_panel=False,
            emit_only=False,
            dry_run=False,
            max_notes=10,
            force=False,
            outbox_path=outbox,
        )
        after = _note_digest(note_path)
        assert after == before
        assert summary.get("skipped_dedup", 0) == 1
        assert summary.get("panel_runs", 0) == 0
    finally:
        _DEDUP_QUEUE.release(dedup_key)
