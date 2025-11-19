from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import NoteUpdateResult, process_note_update
from app.settings.panel_actions import PanelActionMapping


def _note_content(uuid: str, checked: bool) -> str:
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


def _write_snapshot(snapshot_dir: Path, uuid: str, content: str) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{uuid}.md").write_text(content, encoding="utf-8")


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


def test_process_note_update_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_path = tmp_path / "note.md"
    uuid = "note-123"
    snapshot_dir = tmp_path / "snapshots"
    old_content = _note_content(uuid, checked=False)
    new_content = _note_content(uuid, checked=True)
    note_path.write_text(new_content, encoding="utf-8")
    _write_snapshot(snapshot_dir, uuid, old_content)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_update"})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert isinstance(result, NoteUpdateResult)
    assert result.uuid == uuid
    assert result.current_path == note_path.resolve()
    assert result.changed is True
    updated = note_path.read_text(encoding="utf-8")
    assert "- [x]" not in updated
    assert "## AI-logg" in updated
    snapshot_text = (snapshot_dir / f"{uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == updated


def test_process_note_update_detects_stale_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uuid = "note-stale"
    old_content = _note_content(uuid, checked=True)
    original_path = tmp_path / "old" / "note.md"
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_text(old_content, encoding="utf-8")
    new_path = tmp_path / "new" / "note.md"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(old_content, encoding="utf-8")
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(new_path, ctx, expected_path=original_path)

    assert result.stale is True
    assert result.changed is False
    assert new_path.read_text(encoding="utf-8") == old_content


def test_process_note_update_no_panel_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uuid = "note-noop"
    content = textwrap.dedent(
        f"""
        ---
        uuid: {uuid}
        title: Plain
        ---
        
        # Body
        """
    ).strip() + "\n"
    note_path = tmp_path / "note.md"
    note_path.write_text(content, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.changed is False
    assert result.events_count == 0
    assert note_path.read_text(encoding="utf-8") == content
    snapshot_text = (snapshot_dir / f"{uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == content
