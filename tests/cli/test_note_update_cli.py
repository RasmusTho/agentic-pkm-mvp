from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.settings.panel_actions import PanelActionMapping


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


def _write_snapshot(snapshot_dir: Path, uuid: str, content: str) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{uuid}.md").write_text(content, encoding="utf-8")


def _mapping() -> dict[str, PanelActionMapping]:
    return {
        "Skapa en separat sammanfattningsanteckning": PanelActionMapping(
            text="Skapa en separat sammanfattningsanteckning",
            event_type="ask.query.received",
            payload_template={"question": "What now?", "object_id": "cli"},
        )
    }


def _run_cli(args: list[str], env: dict[str, str] | None = None):
    runner = CliRunner()
    return runner.invoke(cli, ["note-update", *args], env=env)


@pytest.fixture(autouse=True)
def disable_panel_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "0")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")


def test_note_update_cli_single_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.services.note_update.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())

    uuid = "note-1"
    note_path = tmp_path / "note.md"
    old_content = _note(uuid, checked=False)
    new_content = _note(uuid, checked=True)
    _write_snapshot(snapshot_dir, uuid, old_content)
    note_path.write_text(new_content, encoding="utf-8")

    result = _run_cli([str(note_path)])

    assert result.exit_code == 0
    updated = note_path.read_text(encoding="utf-8")
    assert "- [x]" not in updated
    assert "Processed 1 notes" in result.output
    assert "changed: 1" in result.output


def test_note_update_cli_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.services.note_update.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())

    dir_path = tmp_path / "vault"
    dir_path.mkdir()
    note_a = dir_path / "a.md"
    note_b = dir_path / "b.md"
    uuid_a = "note-a"
    uuid_b = "note-b"
    _write_snapshot(snapshot_dir, uuid_a, _note(uuid_a, checked=False))
    _write_snapshot(snapshot_dir, uuid_b, _note(uuid_b, checked=False))
    note_a.write_text(_note(uuid_a, checked=True), encoding="utf-8")
    note_b.write_text(_note(uuid_b, checked=False), encoding="utf-8")

    result = _run_cli([str(dir_path), "--glob", "*.md"])

    assert result.exit_code == 0
    assert "a.md" in result.output
    assert "b.md" in result.output
    assert "changed: 1" in result.output
    assert "Processed 2 notes" in result.output
