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


def test_events_doctor_is_bounded_and_read_only(tmp_path: Path) -> None:
    outbox = tmp_path / "index-outbox.jsonl"
    raw = b'{"event":"ask.query.received","trace_id":"T-read-only"}'
    outbox.write_bytes(raw)
    lock_path = outbox.with_name(f".{outbox.name}.append.lock")

    result = CliRunner().invoke(cli, ["events-doctor", "--path", str(outbox)])

    assert result.exit_code == 0
    assert "Trace T-read-only" in result.output
    assert outbox.read_bytes() == raw
    assert not lock_path.exists()


def test_events_doctor_reports_corrupt_outbox(tmp_path: Path) -> None:
    outbox = tmp_path / "index-outbox.jsonl"
    outbox.write_bytes(b'{"event":"ask.query.received"}\n{')

    result = CliRunner().invoke(cli, ["events-doctor", "--path", str(outbox)])

    assert result.exit_code != 0
    assert "Configured event outbox is unreadable" in result.output
