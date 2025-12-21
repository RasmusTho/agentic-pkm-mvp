import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def _write_outbox(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def test_events_tail_parsing_and_diagnostics(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    valid_watch = {
        "event": "watcher.run",
        "timestamp": "2024-01-01T00:00:00Z",
        "trace_id": "t-w",
    }
    valid_panel = {
        "event_type": "panel.intent.executed",
        "created": "2024-01-02T01:00:00Z",
        "trace_id": "t-p",
    }
    lines = [
        json.dumps(valid_watch),
        "{not-json",
        json.dumps(
            {"timestamp": "2024-01-03T00:00:00Z", "trace_id": "t-missing"}
        ),
        json.dumps({"event": "watcher.run", "trace_id": "t-no-ts"}),
        json.dumps(valid_panel),
    ]
    _write_outbox(outbox, lines)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    resp = client.get("/api/events/tail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source_path"] == str(outbox)
    assert data["scanned"] == 5
    assert data["parse_errors"] == 1
    assert data["dropped_missing_fields"] == 2
    assert data["returned"] == 2
    assert len(data.get("events") or []) == 2
    names = {ev["event"] for ev in data.get("events") or []}
    assert {"watcher.run", "panel.intent.executed"}.issubset(names)


def test_events_tail_filters_by_prefix_and_trace(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "events.jsonl"
    lines = [
        json.dumps(
            {
                "event": "watcher.run",
                "timestamp": "2024-01-01T00:00:00Z",
                "trace_id": "first",
            }
        ),
        json.dumps(
            {
                "event": "watcher.poll",
                "timestamp": "2024-01-02T00:00:00Z",
                "trace_id": "second",
            }
        ),
        json.dumps(
            {
                "event": "panel.intent.executed",
                "timestamp": "2024-01-03T00:00:00Z",
                "trace_id": "third",
            }
        ),
    ]
    _write_outbox(outbox, lines)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    prefix_resp = client.get("/api/events/tail", params={"event_prefix": "watcher.", "limit": 1})
    assert prefix_resp.status_code == 200
    prefix_data = prefix_resp.json()
    assert prefix_data["returned"] == 1
    assert prefix_data.get("events")
    assert prefix_data["events"][0]["trace_id"] == "second"

    trace_resp = client.get("/api/events/tail", params={"trace_id": "first"})
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()
    assert trace_data["returned"] == 1
    trace_events = trace_data.get("events") or []
    assert trace_events[0]["trace_id"] == "first"


def test_events_raw_tail_returns_recent_lines(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    raw_lines = ["first line", "second line", "third line"]
    _write_outbox(outbox, raw_lines)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    resp = client.get("/api/events/raw_tail", params={"limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source_path"] == str(outbox)
    assert data["returned"] == 2
    assert data.get("lines") == ["third line", "second line"]
