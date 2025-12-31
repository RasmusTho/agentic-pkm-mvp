from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.stores import reset_store_backends
from app.watcher.vault_watcher import run_watcher_tick

pytestmark = pytest.mark.not_pg


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _panel_note(title: str) -> str:
    return f"""---
uuid: 11111111-1111-1111-1111-111111111111
title: {title}
ai_panel_auto_run: watcher
---
%% AI:Start %%
## AI-instruktion
Do work
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""


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
