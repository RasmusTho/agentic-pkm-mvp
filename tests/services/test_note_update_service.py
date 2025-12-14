from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import NoteUpdateResult, process_note_update
from app.settings.panel_actions import PanelActionMapping
from scripts.yaml_roundtrip import load_frontmatter


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
    assert "> [!info]- AI status" in updated
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


def test_process_note_update_adds_uuid_without_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000A001")
    calls: list[str] = []

    def fake_uuid4() -> uuid.UUID:
        calls.append("called")
        return generated

    monkeypatch.setattr("app.services.note_uuid.uuid.uuid4", fake_uuid4)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text("Just content\n", encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    first_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert first_result.uuid == str(generated)
    assert first_result.uuid_added is True
    assert first_result.changed is False
    after_first = note_path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(after_first)
    assert frontmatter["uuid"] == str(generated)
    assert body.strip() == "Just content"
    assert calls == ["called"]
    snapshot_text = (snapshot_dir / f"{first_result.uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == after_first

    second_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)
    assert second_result.uuid == str(generated)
    assert second_result.uuid_added is False
    assert second_result.changed is False
    assert note_path.read_text(encoding="utf-8") == after_first
    assert calls == ["called"]


def test_process_note_update_adds_uuid_to_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000B002")
    monkeypatch.setattr("app.services.note_uuid.uuid.uuid4", lambda: generated)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text(
        textwrap.dedent(
            """
            ---
            title: Sample Note
            tags:
              - alpha
              - beta
            ---
            
            Body text
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    frontmatter, body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter == {"title": "Sample Note", "tags": ["alpha", "beta"], "uuid": str(generated)}
    assert body.strip() == "Body text"
    assert result.uuid == str(generated)
    assert result.uuid_added is True
    assert result.changed is False
    snapshot_text = (snapshot_dir / f"{result.uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == note_path.read_text(encoding="utf-8")


def test_process_note_update_preserves_existing_uuid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = "stable-uuid-123"
    content = textwrap.dedent(
        f"""
        ---
        uuid: {note_uuid}
        title: Stable
        ---
        
        Body text
        """
    ).strip() + "\n"
    note_path = tmp_path / "note.md"
    note_path.write_text(content, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    first_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)
    after_first = note_path.read_text(encoding="utf-8")

    second_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert first_result.uuid == note_uuid
    assert second_result.uuid == note_uuid
    assert first_result.uuid_added is False
    assert second_result.uuid_added is False
    assert first_result.changed is False
    assert second_result.changed is False
    assert note_path.read_text(encoding="utf-8") == after_first


def test_process_note_update_handles_malformed_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000C003")
    monkeypatch.setattr("app.services.note_uuid.uuid.uuid4", lambda: generated)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text(
        textwrap.dedent(
            """
            ---
            title: "Unclosed
            tags: [alpha
            ---

            Body text
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.uuid == str(generated)
    assert result.uuid_added is True
    assert result.changed is False
    frontmatter, body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter == {"uuid": str(generated)}
    assert body.strip() == "Body text"
