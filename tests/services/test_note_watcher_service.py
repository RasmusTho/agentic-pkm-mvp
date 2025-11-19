from __future__ import annotations

import os
import textwrap
import time
from pathlib import Path

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import DEFAULT_SNAPSHOT_DIR
from app.settings.panel_actions import PanelActionMapping
from app.services.note_watcher import NoteWatcherService


def _note(uuid: str, checked: bool) -> str:
    checkbox = "x" if checked else " "
    return textwrap.dedent(
        f"""
        ---
        uuid: {uuid}
        title: Sample
        ---
        
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [{checkbox}] Skapa en separat sammanfattningsanteckning
        """
    ).strip() + "\n"


def _write_snapshot(snapshot_dir: Path, uuid: str, content: str) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{uuid}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _mapping() -> dict[str, PanelActionMapping]:
    return {
        "Skapa en separat sammanfattningsanteckning": PanelActionMapping(
            text="Skapa en separat sammanfattningsanteckning",
            event_type="ask.query.received",
            payload_template={"question": "What now?", "object_id": "svc"},
        )
    }


@pytest.fixture(autouse=True)
def disable_panel_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "0")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")


def test_scan_vault_once_processes_changed_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.services.note_update.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.services.note_watcher.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())

    vault = tmp_path / "vault"
    vault.mkdir()

    uuid_changed = "note-changed"
    uuid_new = "note-new"
    uuid_clean = "note-clean"

    changed_snapshot = _note(uuid_changed, checked=False)
    changed_current = _note(uuid_changed, checked=True)
    _write_snapshot(snapshot_dir, uuid_changed, changed_snapshot)
    (vault / "changed.md").write_text(changed_current, encoding="utf-8")

    (vault / "new.md").write_text(_note(uuid_new, checked=True), encoding="utf-8")

    clean_content = _note(uuid_clean, checked=False)
    _write_snapshot(snapshot_dir, uuid_clean, clean_content)
    (vault / "clean.md").write_text(clean_content, encoding="utf-8")

    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_watcher"})
    service = NoteWatcherService(vault_root=vault, snapshot_dir=snapshot_dir)

    results = service.scan_vault_once(ctx)

    assert {r.uuid for r in results} == {uuid_changed, uuid_new}
    assert service.last_scan["checked"] == 3
    assert service.last_scan["processed"] == 2
    assert service.last_scan["skipped"] == 1
    assert service.last_scan["errors"] == 0
    assert (snapshot_dir / f"{uuid_new}.md").exists()


def test_scan_vault_once_uses_hash_when_mtime_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.services.note_update.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.services.note_watcher.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())

    vault = tmp_path / "vault"
    vault.mkdir()
    uuid = "note-mtime"
    old_content = _note(uuid, checked=False)
    new_content = _note(uuid, checked=True)

    snapshot_path = _write_snapshot(snapshot_dir, uuid, old_content)
    note_path = vault / "note.md"
    note_path.write_text(new_content, encoding="utf-8")

    now_ts = time.time()
    os.utime(note_path, (now_ts, now_ts))
    os.utime(snapshot_path, (now_ts, now_ts))

    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_watcher"})
    service = NoteWatcherService(vault_root=vault, snapshot_dir=snapshot_dir)

    results = service.scan_vault_once(ctx)

    assert [r.uuid for r in results] == [uuid]
    assert service.last_scan["processed"] == 1
    assert service.last_scan["skipped"] == 0
