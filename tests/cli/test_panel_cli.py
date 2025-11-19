from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.settings.panel_actions import PanelActionMapping


def _write_note(path: Path, checked: bool) -> None:
    checkbox = "x" if checked else " "
    path.write_text(
        textwrap.dedent(
            f"""
            ## AI-instruktion
            Gör något fint.

            ## AI-åtgärder
            - [{checkbox}] Skapa en separat sammanfattningsanteckning
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _ensure_mapping(tmp_path: Path) -> dict[str, PanelActionMapping]:
    return {
        "Skapa en separat sammanfattningsanteckning": PanelActionMapping(
            text="Skapa en separat sammanfattningsanteckning",
            event_type="ask.query.received",
            payload_template={"question": "What now?", "object_id": "cli-panel"},
        )
    }


def _run_panel_cli(args: list[str], env: dict[str, str] | None = None):
    runner = CliRunner()
    return runner.invoke(cli, ["panel-update", *args], env=env)


def test_panel_update_cli_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new_note = tmp_path / "note.md"
    old_note = tmp_path / "note-old.md"
    _write_note(old_note, checked=False)
    _write_note(new_note, checked=True)

    mappings = _ensure_mapping(tmp_path)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mappings)
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "0")

    result = _run_panel_cli([str(new_note), "--old-path", str(old_note)])

    assert result.exit_code == 0
    updated = new_note.read_text(encoding="utf-8")
    assert "- [x]" not in updated
    assert "## AI-logg" in updated
    assert "Panel events: 1 created, 0 dispatched" in result.output


def test_panel_update_cli_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new_note = tmp_path / "note.md"
    old_note = tmp_path / "note-old.md"
    _write_note(old_note, checked=False)
    _write_note(new_note, checked=True)

    mappings = _ensure_mapping(tmp_path)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mappings)
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "1")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")

    result = _run_panel_cli([str(new_note), "--old-path", str(old_note)])

    assert result.exit_code == 0
    updated = new_note.read_text(encoding="utf-8")
    assert "- [x]" not in updated
    assert "Panel events: 1 created, 1 dispatched" in result.output
