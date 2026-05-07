from pathlib import Path
import textwrap

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import apply_promotion_frontmatter, process_note_update
from app.agents.panel.writeback import EXECUTED_FALLBACK
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError


def _note_path(tmp_path: Path) -> Path:
    target = tmp_path / "note.md"
    target.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    return target


def test_apply_promotion_blocked_in_safe_mode(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "maintenance"},
    )
    with pytest.raises(WritesBlockedError) as exc:
        apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert exc.value.state == "safe_mode"
    assert "evergreen" not in path.read_text(encoding="utf-8")


def test_apply_promotion_runs_when_allowed(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "running", "reason": "ok"},
    )
    result = apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert result is True
    assert "evergreen" in path.read_text(encoding="utf-8")
    assert "maturity: evergreen" in path.read_text(encoding="utf-8")


def test_apply_promotion_writes_via_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    writes: list[str] = []

    def _fake_write(note_path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        writes.append(Path(note_path).resolve().relative_to(Path(note_path).anchor).as_posix())
        path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "running", "reason": "ok"},
    )
    monkeypatch.setattr("app.services.note_update.write_note_from_absolute", _fake_write)

    result = apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert result is True
    assert writes


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


def test_panel_runtime_blocked_has_no_file_or_executed_ids_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    prior_fallback_ids = set(EXECUTED_FALLBACK.get(note_uuid, set()))

    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: {})
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "unhealthy", "reason": "probe failing"},
    )
    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_update"})

    with pytest.raises(WritesBlockedError) as exc:
        process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert exc.value.action == "panel runtimes"
    assert exc.value.state == "unhealthy"
    assert exc.value.reason == "probe failing"
    assert note_path.read_text(encoding="utf-8") == before
    assert set(EXECUTED_FALLBACK.get(note_uuid, set())) == prior_fallback_ids
