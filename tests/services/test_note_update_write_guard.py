from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import apply_promotion_frontmatter, process_note_update
from app.write_guard import WritesBlockedError


def _promotion_note(path: Path) -> None:
    path.write_text("---\nuuid: note-1\nreview_state: inbox\n---\nBody\n", encoding="utf-8")


def _panel_markdown(note_uuid: str, *, checked: bool) -> str:
    checkbox = "x" if checked else " "
    return textwrap.dedent(
        f"""
        ---
        uuid: {note_uuid}
        title: Sample
        ---

        ## AI-åtgärder
        - [{checkbox}] Skapa en separat sammanfattningsanteckning
        """
    ).strip() + "\n"


def test_promotion_write_is_blocked_before_file_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_path = tmp_path / "note.md"
    _promotion_note(note_path)
    before = note_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "app.services.note_update.DEFAULT_WRITE_GUARD.snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "maintenance"},
    )

    with pytest.raises(WritesBlockedError) as exc:
        apply_promotion_frontmatter(note_path, "note-1", "evergreen")

    assert exc.value.action == "promotion frontmatter"
    assert exc.value.state == "safe_mode"
    assert exc.value.reason == "maintenance"
    assert note_path.read_text(encoding="utf-8") == before


def test_panel_runtime_write_is_blocked_before_file_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_uuid = "panel-note-1"
    note_path = tmp_path / "note.md"
    old_markdown = _panel_markdown(note_uuid, checked=False)
    new_markdown = _panel_markdown(note_uuid, checked=True)
    note_path.write_text(new_markdown, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{note_uuid}.md").write_text(old_markdown, encoding="utf-8")
    before = note_path.read_text(encoding="utf-8")

    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: {})
    monkeypatch.setattr(
        "app.services.note_update.DEFAULT_WRITE_GUARD.snapshot_fn",
        lambda: {"state": "unhealthy", "reason": "probe failing"},
    )
    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_update"})

    with pytest.raises(WritesBlockedError) as exc:
        process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert exc.value.action == "panel runtimes"
    assert exc.value.state == "unhealthy"
    assert exc.value.reason == "probe failing"
    assert note_path.read_text(encoding="utf-8") == before

