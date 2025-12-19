from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli.__init__ import cli
from app.events.schema import make_outbox_event


def test_events_doctor_renders_story(tmp_path: Path) -> None:
    outbox = tmp_path / "index-outbox.jsonl"
    events = [
        make_outbox_event(
            "ask.query.received",
            source="api",
            payload={"object_id": "obj-1"},
            trace_id="T-story",
            timestamp="2025-01-01T00:00:00Z",
        ).model_dump(),
        make_outbox_event(
            "index.embedding.created",
            source="indexer",
            payload={"object_id": "obj-1"},
            trace_id="T-story",
            timestamp="2025-01-01T00:00:01Z",
        ).model_dump(),
    ]
    outbox.write_text("\n".join(json.dumps(ev) for ev in events) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["events-doctor", "--path", str(outbox), "--trace-id", "T-story"])

    assert result.exit_code == 0
    assert "Trace T-story" in result.output
    assert "ask.query.received" in result.output
    assert "index.embedding.created" in result.output
