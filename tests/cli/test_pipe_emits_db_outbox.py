from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.events.types import INGEST_OBJECT_CREATED
from tests.helpers.pkm_alpha_helper import reset_memory_stores


def test_pipe_emits_db_outbox_event(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    note = tmp_path / "note.md"
    note.write_text("# pipe emit", encoding="utf-8")
    outbox_path = tmp_path / "outbox.jsonl"
    captured: list = []

    def fake_write_outbox(event, *args, **kwargs):
        captured.append(event)
        return ""

    monkeypatch.setattr("app.cli.write_outbox_event", fake_write_outbox)

    runner = CliRunner()
    env = {
        "STORE_BACKEND": "memory",
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PIPE_EMIT_DB_OUTBOX": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }

    result = runner.invoke(cli, ["pipe", str(note), "--json"], env=env)
    assert result.exit_code == 0, result.output
    assert len(captured) == 1

    event = captured[0]
    assert event.event_type == INGEST_OBJECT_CREATED
    payload = event.payload
    assert payload.get("object_id"), "expected object_id in payload"
    assert payload.get("source_ref") == str(note)
