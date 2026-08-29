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
    assert data.get("source_path") == str(outbox)
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

    resp_trace = client.get("/api/events/tail", params={"trace_id": "t2"})
    assert resp_trace.status_code == 200
    traces = [ev.get("trace_id") for ev in resp_trace.json().get("events") or []]
    assert traces == ["t2"]


def test_events_tail_is_read_only_for_unterminated_outbox(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    raw = b'{"event":"watcher.run","trace_id":"unterminated"}'
    outbox.write_bytes(raw)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    lock_path = outbox.with_name(f".{outbox.name}.append.lock")

    response = TestClient(app).get("/api/events/tail")

    assert response.status_code == 200
    assert response.json()["events"][0]["trace_id"] == "unterminated"
    assert outbox.read_bytes() == raw
    assert not lock_path.exists()


def test_events_tail_reports_corrupt_outbox_without_mutating_it(
    tmp_path: Path, monkeypatch
) -> None:
    outbox = tmp_path / "outbox.jsonl"
    raw = b'{"event":"watcher.run"}\n{'
    outbox.write_bytes(raw)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    lock_path = outbox.with_name(f".{outbox.name}.append.lock")

    response = TestClient(app).get("/api/events/tail")

    assert response.status_code == 503
    assert response.json()["detail"] == "configured event outbox is unreadable"
    assert outbox.read_bytes() == raw
    assert not lock_path.exists()
