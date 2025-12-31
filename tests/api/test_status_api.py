import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.observability import status_service


def test_status_endpoint_returns_snapshot():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "timestamp" in body
    assert body.get("sot_version")
    assert body.get("sot_baseline_version")
    assert body.get("sot_forward_line_version")
    assert isinstance(body.get("stores"), list)
    assert body.get("feature_line_version") == body.get("sot_forward_line_version")
    assert isinstance(body.get("active_features"), list)
    intents = body.get("intents") or {}
    assert "promote_created_total" in intents
    events = body.get("events") or {}
    assert "panel_runs_total" in events
    assert "watcher_runs_total" in events
    assert "promotion_executed_total" in events
    assert isinstance(events.get("ingest_runs_by_plane", {}), dict)

    events_log = body.get("events_log") or {}
    assert "path" in events_log
    assert "total_lines" in events_log

    worker_queue = body.get("worker_queue") or {}
    assert "mode" in worker_queue


def test_status_counts_watcher_runs(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    watcher_event = {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z"}
    outbox.write_text(json.dumps(watcher_event) + "\n", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    status_service.INDEX_OUTBOX_PATH = str(outbox)

    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    events = data.get("events") or {}
    assert events.get("watcher_runs_total", 0) >= 1

    events_log = data.get("events_log") or {}
    assert events_log.get("total_lines") == 1
