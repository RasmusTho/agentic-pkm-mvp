from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.events.schema import OutboxEvent


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_events_doctor_json_story_orders_and_stages(monkeypatch, tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    trace_id = "trace-123"

    rows = [
        OutboxEvent(event="watcher.run", trace_id=trace_id, source="watcher", payload={}).model_dump(mode="json"),
        OutboxEvent(event="panel.intent.created", trace_id=trace_id, source="panel", payload={}).model_dump(mode="json"),
        OutboxEvent(event="promote.intent.created", trace_id=trace_id, source="panel", payload={}).model_dump(mode="json"),
        OutboxEvent(event="promote.done", trace_id=trace_id, source="promotion", payload={}).model_dump(mode="json"),
        OutboxEvent(event="watcher.run", trace_id="trace-other", source="watcher", payload={}).model_dump(mode="json"),
    ]
    _write_jsonl(outbox, rows)

    runner = CliRunner()
    result = runner.invoke(cli, ["events", "doctor", "--outbox", str(outbox), "--trace-id", trace_id, "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)

    assert data["trace_id"] == trace_id
    assert data["count"] == 4
    assert data["stages"] == ["watcher", "panel", "promote"]
    assert [e["event"] for e in data["events"]] == [
        "watcher.run",
        "panel.intent.created",
        "promote.intent.created",
        "promote.done",
    ]


def test_events_doctor_missing_trace_exits_2(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    _write_jsonl(outbox, [])
    runner = CliRunner()
    result = runner.invoke(cli, ["events", "doctor", "--outbox", str(outbox), "--trace-id", "nope", "--json"])
    assert result.exit_code == 2
