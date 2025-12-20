import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def test_events_tail_returns_last_events(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    events = [
        {"event": "panel.intent.created", "trace_id": "t1", "timestamp": "2024-01-01T00:00:00Z"},
        {"event": "watcher.run", "trace_id": "t2", "timestamp": "2024-01-02T00:00:00Z"},
        {"event": "watcher.run", "trace_id": "t3", "timestamp": "2024-01-03T00:00:00Z"},
    ]
    outbox.write_text("\n".join(json.dumps(ev) for ev in events), encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    resp = client.get("/api/events/tail", params={"limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    returned = data.get("events") or []
    assert len(returned) == 2
    # Newest-first
    assert returned[0]["trace_id"] == "t3"
    assert returned[1]["trace_id"] == "t2"

    resp_filtered = client.get("/api/events/tail", params={"event_prefix": "panel"})
    assert resp_filtered.status_code == 200
    filtered = resp_filtered.json().get("events") or []
    assert len(filtered) == 1
    assert filtered[0]["event"].startswith("panel")
