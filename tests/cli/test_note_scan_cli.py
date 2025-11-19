from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.services.note_update import DEFAULT_SNAPSHOT_DIR
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
    return runner.invoke(cli, ["note-scan", *args], env=env)


@pytest.fixture(autouse=True)
def disable_panel_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "0")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")


def test_note_scan_cli_detects_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.services.note_update.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.services.note_watcher.DEFAULT_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())

    vault = tmp_path / "vault"
    vault.mkdir()

    uuid_changed = "note-1"
    uuid_clean = "note-2"

    _write_snapshot(snapshot_dir, uuid_changed, _note(uuid_changed, checked=False))
    (vault / "changed.md").write_text(_note(uuid_changed, checked=True), encoding="utf-8")

    clean_content = _note(uuid_clean, checked=False)
    _write_snapshot(snapshot_dir, uuid_clean, clean_content)
    (vault / "clean.md").write_text(clean_content, encoding="utf-8")

    result = _run_cli([str(vault), "--glob", "*.md"])

    assert result.exit_code == 0
    assert "changed.md" in result.output
    assert "updated" in result.output
    assert "clean.md" in result.output
    assert "skipped" in result.output
    assert "Scanned 2 notes" in result.output
    assert "processed: 1" in result.output
    assert "skipped: 1" in result.output
